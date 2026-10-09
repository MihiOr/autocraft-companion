"""Surgical JBeam edits (not a strict JSON reserializer), archive validation and backups."""
import base64
from dataclasses import dataclass
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import secrets
import shutil
import tempfile
import zipfile

MANIFEST = '_autocraft_companion.json'


class PatchError(ValueError):
    pass


TOKEN = re.compile(r'//[^\r\n]*|/\*.*?\*/|"(?:\\.|[^"\\])*"|[{}\[\]:,]|[^\s{}\[\]:,]+', re.S)


@dataclass
class Token:
    value: str
    start: int
    end: int


class JBeam:
    """Read spans even in AutoCraft's comma-optional JBeam. Never execute expressions."""
    def __init__(self, text):
        self.text = text
        self.tokens = [Token(m[0], m.start(), m.end()) for m in TOKEN.finditer(text)
                       if not m[0].startswith(('//', '/*'))]
        self.ends = {}
        stack = []
        for i, t in enumerate(self.tokens):
            if t.value in ('{', '['):
                stack.append(i)
            elif t.value in ('}', ']'):
                if not stack:
                    raise PatchError('Unbalanced JBeam brackets.')
                start = stack.pop()
                if (self.tokens[start].value, t.value) not in (('{', '}'), ('[', ']')):
                    raise PatchError('Mismatched JBeam brackets.')
                self.ends[start] = i
        if stack:
            raise PatchError('Unbalanced JBeam brackets.')

    def props(self, obj):
        end = self.ends[obj]
        i = obj + 1
        found = []
        while i < end:
            t = self.tokens[i]
            if t.value.startswith('"') and i + 2 < end and self.tokens[i + 1].value == ':':
                v = i + 2
                found.append((json.loads(t.value), v))
                i = self.ends.get(v, v) + 1
            else:
                i = self.ends.get(i, i) + 1
        return found

    def prop(self, obj, name):
        values = [v for k, v in self.props(obj) if k == name]
        if len(values) != 1:
            raise PatchError(f'Expected one {name} setting, found {len(values)}.')
        return values[0]

    def span(self, i):
        return self.tokens[i].start, self.tokens[self.ends.get(i, i)].end


def edits(text, replacements):
    for start, end, value in sorted(replacements, reverse=True):
        text = text[:start] + value + text[end:]
    return text


def number(settings, key, low, high, optional=False):
    raw = str(settings.get(key, '')).strip().replace(',', '.')
    if not raw and optional:
        return None
    try:
        value = float(raw)
    except ValueError:
        raise PatchError(f'{key.replace("_", " ")}: enter a number.') from None
    if not math.isfinite(value) or not low <= value <= high:
        raise PatchError(f'{key.replace("_", " ")}: use a value from {low} to {high}.')
    return value


def validate_settings(s):
    result = {'clear_glass': bool(s.get('clear_glass', False))}
    result['suspension_enabled'] = bool(s.get('suspension_enabled', True))
    result['suspension_absolute'] = bool(s.get('suspension_absolute', False))
    for axle in ('front', 'rear'):
        enabled=result['suspension_enabled']
        result[axle + '_lift'] = number(s, axle + '_lift', 0, 500) if enabled and not result['suspension_absolute'] else 0
        result[axle + '_length'] = number(s, axle + '_length', 1, 3000, True) if enabled and result['suspension_absolute'] else None
        result[axle + '_rate'] = number(s, axle + '_rate', 1, 2000000, True) if enabled else None
        result[axle + '_damping'] = number(s, axle + '_damping', 0, 200000, True) if enabled else None
        if enabled and result['suspension_absolute']:
            for field, low, high in (('length',1,3000),('rate',1,2000000),('damping',0,200000)):
                key = axle + '_' + field
                if result[key] is None:
                    continue
                multiplier_key = key + '_multiplier'
                multiplier = number({multiplier_key:s.get(multiplier_key,1)}, multiplier_key,0,100)
                result[key] = number({key:result[key]*multiplier},key,low,high)
    result['glass_opacity'] = number(s, 'glass_opacity', 0.01, 0.4)
    result['kingpin_stops_enabled'] = bool(s.get('kingpin_stops_enabled', False))
    if result['kingpin_stops_enabled']:
        for axle in ('front','rear'):
            key = 'kingpin_'+axle+'_angle'
            result[key] = number({key:s.get(key,45)},key,5,45)
    return result


def patch_engine(text):
    doc = JBeam(text)
    root = doc.prop(0, 'engine')
    engine = doc.prop(root, 'mainEngine')
    torque = doc.prop(engine, 'torque')
    torque_end = doc.ends.get(torque)
    if torque_end is None or doc.tokens[torque].value != '[':
        raise PatchError('Engine torque table is not an array.')
    old = [v for k, v in doc.props(engine) if k == 'starterMaxRPM']
    if len(old) > 1:
        raise PatchError('Duplicate starterMaxRPM fields.')
    # Remove an existing field and insert exactly once immediately after torque.
    replacements = []
    if old:
        v = old[0]
        start = doc.tokens[v - 2].start
        end = doc.span(v)[1]
        if v + 1 < len(doc.tokens) and doc.tokens[v + 1].value == ',':
            end = doc.tokens[v + 1].end
        replacements.append((start, end, ''))
    end = doc.tokens[torque_end].end
    comma = torque_end + 1 < len(doc.tokens) and doc.tokens[torque_end + 1].value == ','
    if comma:
        end = doc.tokens[torque_end + 1].end
    newline = '\r\n' if '\r\n' in text else '\n'
    replacements.append((end, end, ('' if comma else ',') + newline + '\t\t\t"starterMaxRPM":500,'))
    result = edits(text, replacements)
    check = JBeam(result)
    check.prop(check.prop(check.prop(0, 'engine'), 'mainEngine'), 'starterMaxRPM')
    return result


def patch_suspension(text, axle, options):
    letter = 'F' if axle == 'front' else 'R'
    doc = JBeam(text)
    coils = doc.prop(0, 'coils_' + letter)
    beams = doc.prop(coils, 'beams')
    replacements = []
    springs, preload = [], []
    for i in range(beams + 1, doc.ends[beams]):
        if doc.tokens[i].value == '{':
            for key, v in doc.props(i):
                if key == 'beamSpring':
                    springs.append(v)
                if key == 'beamPrecompression':
                    preload.append(v)
    if len(springs) != 1 or len(preload) != 1:
        raise PatchError(f'Unsupported {axle} coil layout; no changes installed.')
    v = springs[0]
    original_rate = float(doc.tokens[v].value)
    rate = options[axle + '_rate']
    if rate is None:
        rate = original_rate
    if rate <= 0:
        raise PatchError(f'{axle.title()} spring stiffness is {rate:g}. Fix the export or set a positive override.')
    replacements.append((*doc.span(v), f'{rate:g}'))
    v = preload[0]
    expression = json.loads(doc.tokens[v].value)
    # Only accept the exact known exporter expression to avoid guessing at new formats.
    pattern = r'\$=\(1\+\$RH_' + letter + r'\*([-+0-9.eE]+)\)\*([-+0-9.eE]+)'
    match = re.fullmatch(pattern, expression)
    if not match or float(match[2]) <= 0:
        raise PatchError(f'{axle.title()} spring precompression is invalid or unsupported. Re-export with working load-capacity values.')
    base = float(match[2]) * (1 + options[axle + '_lift'] / 100)
    new_expression = f'$=(1+$RH_{letter}*{match[1]})*{base:.10g}'
    replacements.append((*doc.span(v), json.dumps(new_expression)))
    # Optional damping controls modify both default and its UI maximum.
    damping = options[axle + '_damping']
    row_pattern = re.compile(r'(\["\$Damp_(?:bump|rebd)_' + letter +
                             r'",\s*"range",\s*"Ns/m",\s*"[^"]+",\s*)([-+0-9.eE]+)(,\s*)([-+0-9.eE]+)(,\s*)([-+0-9.eE]+)')
    matches = list(row_pattern.finditer(text))
    if len(matches) != 2:
        raise PatchError(f'Unsupported {axle} damper settings.')
    for m in matches:
        default, minimum, maximum = map(float, (m[2], m[4], m[6]))
        if damping is None:
            if not 0 <= minimum <= default <= maximum:
                raise PatchError(f'{axle.title()} damping is invalid. Set a damping override or fix the export.')
        else:
            replacements.append((m.start(2), m.end(6), f'{damping:g}, 0, {max(damping * 2, 1):g}'))
    return edits(text, replacements)


def patch_glass(text, opacity):
    data = json.loads(text)
    count = 0
    for key, mat in data.items():
        if not isinstance(mat, dict) or not (key.lower() == 'glass' or str(mat.get('mapTo', '')).lower() == 'glass'):
            continue
        mat['dynamicCubemap'] = False
        mat.pop('cubemap', None)
        mat['translucent'] = True
        mat['castShadows'] = False
        for stage in mat.get('Stages', []):
            stage['metallicFactor'] = 0
            stage['roughnessFactor'] = 0.2
            stage['pixelSpecular'] = False
            stage['opacityFactor'] = opacity
            stage['diffuseColor'] = [255, 255, 255, round(opacity * 255)]
        count += 1
    if count != 1:
        raise PatchError('Expected one AutoCraft Glass material; clear glass was not applied.')
    return json.dumps(data, indent=2) + '\n'


def validate_archive(z):
    names = z.namelist()
    if len(names) != len(set(n.casefold() for n in names)):
        raise PatchError('Duplicate ZIP entries.')
    if sum(i.file_size for i in z.infolist()) > 1024**3 or any(i.file_size > 250 * 1024**2 for i in z.infolist()):
        raise PatchError('Archive exceeds supported size limits.')
    for n in names:
        p = PurePosixPath(n)
        if p.is_absolute() or '..' in p.parts or '\\' in n or ':' in n:
            raise PatchError('Unsafe archive path.')
    bad = z.testzip()
    if bad:
        raise PatchError('Damaged ZIP entry: ' + bad)


def vehicle_roots(names):
    return {n.split('/')[1] for n in names
            if n.startswith('vehicles/') and len(n.split('/')) == 3 and n.endswith('/engine.jbeam')}


def patch_zip(source, target, settings):
    options = validate_settings(settings)
    source, target = Path(source), Path(target)
    if source.resolve() == target.resolve():
        raise PatchError('Patch output must differ from the original download.')
    target.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(source) as zin:
        validate_archive(zin)
        roots = vehicle_roots(zin.namelist())
        if len(roots) != 1:
            raise PatchError('Expected exactly one AutoCraft vehicle in ZIP.')
        root = next(iter(roots))
        prefix = f'vehicles/{root}/'
        original = {}
        generated = []
        if MANIFEST in zin.namelist():
            manifest = json.loads(zin.read(MANIFEST))
            if manifest.get('version') != 1:
                raise PatchError('Unknown companion manifest version.')
            original = {k: base64.b64decode(v, validate=True) for k, v in manifest['originals'].items()}
            generated = manifest.get('generated', [])
        baseline = {n: zin.read(n) for n in zin.namelist() if n != MANIFEST and n not in generated}
        baseline.update(original)
        changed = {}
        for file in ('engine.jbeam', 'suspension_F.jbeam', 'suspension_R.jbeam', 'main.materials.json'):
            name = prefix + file
            if name not in baseline:
                raise PatchError('Missing ' + name)
            raw = baseline[name]
            original[name] = raw
            text = raw.decode('utf-8-sig')
            if file == 'engine.jbeam':
                text = patch_engine(text)
            elif file.startswith('suspension_'):
                if options['suspension_enabled'] and not options['suspension_absolute']:
                    text = patch_suspension(text, 'front' if '_F.' in file else 'rear', options)
            elif options['clear_glass']:
                text = patch_glass(text, options['glass_opacity'])
            changed[name] = text.encode('utf-8')
        output_entries = dict(baseline)
        output_entries.update(changed)
        if settings.get('kingpin_stops_enabled', False):
            from kingpin_patch import apply as apply_joints
            output_entries = apply_joints(output_entries, prefix, settings)
        if settings.get('electric_enabled', False):
            from electric_patch import convert
            output_entries = convert(output_entries, root, settings)
            if settings.get('ev_weight_enabled', False):
                from weight_patch import apply_weight
                output_entries = apply_weight(output_entries, prefix, settings)
            # Old saved modes must never silently reinstall the legacy slip controller.
            from tire_ecu_patch import apply
            output_entries = apply(output_entries, prefix, dict(settings, ev_ecu_mode='Custom Lua'))
            from ev_sound_patch import apply as apply_sound
            output_entries = apply_sound(output_entries, prefix, settings)
            from custom_control import verify_motor_wiring
            verify_motor_wiring(output_entries)
        if options['suspension_enabled'] and options['suspension_absolute']:
            from suspension_values import apply_absolute
            output_entries = apply_absolute(output_entries, prefix, options)
        if settings.get('wheel_attachment_enabled', False):
            from wheel_attachment_patch import apply as apply_wheel_attachment
            output_entries = apply_wheel_attachment(output_entries, prefix, settings)
        if settings.get('latch_patch_enabled', False):
            from latch_patch import apply as apply_latches
            output_entries = apply_latches(output_entries, prefix)
        if settings.get('spawn_heading_enabled', False):
            from spawn_heading_patch import apply as apply_spawn_heading
            output_entries = apply_spawn_heading(output_entries, prefix)
        if settings.get('steering_response_enabled', False):
            from steering_response_patch import apply as apply_steering_response
            output_entries = apply_steering_response(output_entries, prefix, settings)
        if settings.get('toe_stability_enabled', False):
            from toe_stability_patch import apply as apply_toe_stability
            output_entries = apply_toe_stability(output_entries, prefix, dict(settings,toe_stability_enabled=True))
        if settings.get('rack_mount_enabled', False):
            from rack_mount_patch import apply as apply_rack_mounts
            output_entries = apply_rack_mounts(output_entries, prefix)
        if settings.get('export_version_label', False):
            # Exporters can retain an older design name after saving as v20 etc.
            # Keep that name, but expose the filename version in the selector.
            label = re.sub(r'_\d{12}$', '', root)
            info_name = prefix+'info.json'
            info = json.loads(output_entries[info_name])
            title = str(info.get('Name', label))
            if not title.startswith(label):
                title = label+' - '+title
            info['Name'] = title
            if prefix+'default.pc' in output_entries:
                info['default_pc'] = 'default'
            output_entries[info_name] = (json.dumps(info,indent=2)+'\n').encode()
            main_name = prefix+'main.jbeam'
            text = output_entries[main_name].decode('utf-8-sig')
            doc = JBeam(text)
            value = doc.prop(doc.prop(doc.prop(0,'main'),'information'),'name')
            output_entries[main_name] = edits(text,[(*doc.span(value),json.dumps(title))]).encode()
        # Remember all modified/removed source entries so EV conversion can be
        # reapplied or turned off without stacking edits or losing ICE originals.
        for name, raw in baseline.items():
            if output_entries.get(name) != raw:
                original[name] = raw
        generated = [name for name in output_entries if name not in baseline]
        fd, tmp = tempfile.mkstemp(suffix='.tmp', dir=target.parent)
        os.close(fd)
        try:
            with zipfile.ZipFile(tmp, 'w', zipfile.ZIP_DEFLATED) as zout:
                for name, raw in output_entries.items():
                    zout.writestr(name, raw)
                zout.writestr(MANIFEST, json.dumps({'version': 1, 'options': options, 'generated': generated,
                    'originals': {k: base64.b64encode(v).decode() for k, v in original.items()}}))
            with zipfile.ZipFile(tmp) as check:
                validate_archive(check)
            os.replace(tmp, target)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)
    return root


def renamed_zip(source, target, root, new_root, suffix):
    """Give a duplicate its own vehicle folder and update local asset paths."""
    with zipfile.ZipFile(source) as zin:
        prefix = f'vehicles/{root}/'
        paths = {prefix: f'vehicles/{new_root}/'}
        for name in zin.namelist():
            bits = name.split('/')
            if len(bits) > 2 and bits[0] == 'vehicles' and bits[1] != root:
                paths[f'vehicles/{bits[1]}/'] = f'vehicles/{new_root}/companion_assets/{bits[1]}/'

        def relocate(name):
            for old, new in paths.items():
                if name.startswith(old):
                    return new + name[len(old):]
            return name

        def display_name(value):
            title = str(value)
            label = re.sub(r'_\d{12}$', '', root)
            # Keep the installed filename/version together in selector search
            # and sorting, rather than appending it after the design name.
            if suffix.startswith('_') and title.startswith(label):
                return label + suffix + title[len(label):]
            return title + (suffix if suffix.startswith('_') else (' ' + suffix if suffix else ''))

        def transform(name, raw):
            if Path(name).suffix.lower() in ('.json', '.jbeam', '.dae', '.pc', '.lua', '.cs'):
                for old, new in paths.items():
                    raw = raw.replace(old.encode(), new.encode())
            if name == prefix + 'info.json':
                data = json.loads(raw.decode('utf-8-sig'))
                data['Name'] = display_name(data.get('Name', root))
                raw = (json.dumps(data, indent=2) + '\n').encode()
            elif name == prefix + 'main.jbeam':
                text = raw.decode('utf-8-sig')
                doc = JBeam(text)
                value = doc.prop(doc.prop(doc.prop(0, 'main'), 'information'), 'name')
                raw = edits(text, [(*doc.span(value), json.dumps(display_name(json.loads(doc.tokens[value].value))))]).encode()
            return raw

        if prefix + 'info.json' not in zin.namelist():
            raise PatchError('Missing info.json; cannot name the duplicate vehicle.')
        with zipfile.ZipFile(target, 'w', zipfile.ZIP_DEFLATED) as zout:
            for info in zin.infolist():
                raw = zin.read(info)
                if info.filename == MANIFEST:
                    manifest = json.loads(raw)
                    manifest['originals'] = {relocate(n): base64.b64encode(transform(n, base64.b64decode(v))).decode()
                                             for n, v in manifest['originals'].items()}
                    manifest['generated'] = [relocate(n) for n in manifest.get('generated', [])]
                    raw = json.dumps(manifest).encode()
                else:
                    raw = transform(info.filename, raw)
                info.filename = relocate(info.filename)
                zout.writestr(info, raw)


def install_zip(source, mods, backup_root):
    """Install under a free name, preserving every existing mod."""
    source, mods, backup_root = Path(source).resolve(), Path(mods).resolve(), Path(backup_root).resolve()
    if mods == backup_root or mods in backup_root.parents:
        raise PatchError('Backups must be outside the BeamNG mods folder.')
    with zipfile.ZipFile(source) as z:
        validate_archive(z)
        roots = vehicle_roots(z.namelist())
        needs_spawn_helper = any(n.endswith('/companion_spawn_heading.json') for n in z.namelist())
    if len(roots) != 1:
        raise PatchError('Cannot identify one vehicle to install.')
    root = next(iter(roots))
    mods.mkdir(parents=True, exist_ok=True)
    if needs_spawn_helper:
        from spawn_heading_patch import install_helper
        install_helper(mods, backup_root)
    fd, tmp = tempfile.mkstemp(prefix='.companion-', suffix='.tmp', dir=mods)
    os.close(fd)
    try:
        pattern = re.compile(re.escape(root) + r'_(\d+)$', re.I)
        names = [p.stem if p.suffix.lower() == '.zip' else p.name for p in mods.iterdir()]
        if (mods / 'unpacked').is_dir():
            names.extend(p.name for p in (mods / 'unpacked').iterdir())
        highest = max((int(m[1]) for name in names if (m := pattern.fullmatch(name))), default=0)
        duplicate = highest > 0
        next_number = highest + 1
        while True:
            suffix = ''
            if duplicate:
                suffix = f'{next_number:02d}'
                next_number += 1
            stem = root + ('_' + suffix if suffix else '')
            target = mods / (stem + '.zip')
            # Inspect names only, never the contents of installed packages.
            if target.exists() or (mods / stem).exists() or (mods / 'unpacked' / stem).exists():
                duplicate = True
                continue
            if duplicate:
                new_root = root + '_' + str(100000000000 + secrets.randbelow(900000000000))
                renamed_zip(source, tmp, root, new_root, '_' + suffix)
            else:
                shutil.copyfile(source, tmp)
            with zipfile.ZipFile(tmp) as check:
                validate_archive(check)
            try:
                # Windows rename never replaces an existing destination. On other
                # platforms, a hard link publishes the staged file without replacing.
                if os.name == 'nt':
                    os.rename(tmp, target)
                else:
                    os.link(tmp, target)
                break
            except FileExistsError:
                duplicate = True
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return target, None
