"""Read effective AutoCraft coil/damper values; never execute JBeam expressions."""
import ast
import json
import math
import operator
import re
import zipfile

from electric_patch import rows, values, node_positions
from patcher import JBeam, PatchError, edits, validate_archive, vehicle_roots


def evaluate(raw, variables):
    if isinstance(raw,(int,float)):
        result=float(raw)
    else:
        expr=str(raw)
        if expr.startswith('$='):expr=expr[2:]
        def variable(match):
            key=match[0]
            if key not in variables:raise PatchError('Unknown suspension variable '+key)
            return repr(float(variables[key]))
        expr=re.sub(r'\$[A-Za-z_][A-Za-z_0-9]*',variable,expr)
        if len(expr)>1000:raise PatchError('Suspension expression is too long.')
        def calc(node):
            if isinstance(node,ast.Constant) and type(node.value) in (int,float):return node.value
            if isinstance(node,ast.UnaryOp) and isinstance(node.op,(ast.UAdd,ast.USub)):
                return calc(node.operand)*(1 if isinstance(node.op,ast.UAdd) else -1)
            ops={ast.Add:operator.add,ast.Sub:operator.sub,ast.Mult:operator.mul,ast.Div:operator.truediv}
            if isinstance(node,ast.BinOp) and type(node.op) in ops:return ops[type(node.op)](calc(node.left),calc(node.right))
            raise PatchError('Unsupported suspension expression; no code was executed.')
        try:result=float(calc(ast.parse(expr,mode='eval').body))
        except (SyntaxError,ValueError,ZeroDivisionError,OverflowError,RecursionError) as e:
            raise PatchError('Invalid suspension expression.') from e
    if not math.isfinite(result):raise PatchError('Non-finite suspension value.')
    return result


def beam_rows(doc, table):
    state={};i=table+1
    while i<doc.ends[table]:
        token=doc.tokens[i].value
        if token=='{':state.update(dict(doc.props(i)))
        elif token=='[':
            vals=values(doc,i)
            if vals and vals[0]!='id1:':
                local=dict(state);inline=None;j=i+1
                while j<doc.ends[i]:
                    if doc.tokens[j].value=='{':inline=j;local.update(dict(doc.props(j)))
                    j=doc.ends.get(j,j)+1
                yield i,vals,local,inline
        i=doc.ends.get(i,i)+1


def inspect_entries(entries,prefix):
    variables={};positions={};docs={}
    for name,raw in entries.items():
        if not name.startswith(prefix) or not name.endswith('.jbeam'):continue
        text=raw.decode('utf-8-sig');doc=JBeam(text);docs[name]=doc
        positions.update(node_positions(text))
        for _,part in doc.props(0):
            for key,table in doc.props(part):
                if key=='variables':
                    for row in rows(doc,table):
                        v=values(doc,row)
                        if len(v)>4 and str(v[0]).startswith('$'):variables[v[0]]=v[4]
    info=json.loads(entries.get(prefix+'info.json',b'{}'))
    config=prefix+str(info.get('default_pc','default'))+'.pc'
    if entries.get(config,b'').strip():
        pc=json.loads(entries[config]);variables.update(pc.get('vars',{}))
    result={};details={}
    for axle,letter in (('front','F'),('rear','R')):
        name=prefix+'suspension_'+letter+'.jbeam'
        if name not in docs:raise PatchError('ZIP does not have the supported AutoCraft suspension layout.')
        doc=docs[name];measure={}
        for section in ('coils','dampers'):
            table=doc.prop(doc.prop(0,section+'_'+letter),'beams')
            records=list(beam_rows(doc,table))
            if len(records)!=2:raise PatchError('Expected two '+section+' per axle in this AutoCraft export.')
            for _,nodes,props,_ in records:
                def get(key,default):
                    return evaluate(json.loads(doc.tokens[props[key]].value) if key in props else default,variables)
                if section=='coils':
                    try:span=math.dist(positions[nodes[0]],positions[nodes[1]])
                    except KeyError as e:raise PatchError('Missing spring endpoint.') from e
                    measure.setdefault('length',[]).append(span*get('beamPrecompression',1)*1000)
                    measure.setdefault('rate',[]).append(get('beamSpring',0))
                else:measure.setdefault('damping',[]).append(get('beamDamp',0))
        for key,vals in measure.items():
            result[axle+'_'+key]=sum(vals)/len(vals)
            details[axle+'_'+key]=vals
    return result,details,positions,docs


def read_zip(path):
    with zipfile.ZipFile(path) as z:
        validate_archive(z);roots=vehicle_roots(z.namelist())
        if len(roots)!=1:raise PatchError('Select a ZIP containing one AutoCraft vehicle.')
        entries={n:z.read(n) for n in z.namelist()}
    vals,details,_,_=inspect_entries(entries,'vehicles/'+next(iter(roots))+'/')
    return vals,details


def apply_absolute(entries,prefix,options):
    _,_,positions,docs=inspect_entries(entries,prefix)
    result=dict(entries)
    for axle,letter in (('front','F'),('rear','R')):
        name=prefix+'suspension_'+letter+'.jbeam';doc=docs[name];changes=[]
        for section in ('coils','dampers'):
            table=doc.prop(doc.prop(0,section+'_'+letter),'beams')
            for row,nodes,props,inline in beam_rows(doc,table):
                overrides={}
                if section=='coils':
                    if options[axle+'_rate'] is not None:overrides['beamSpring']=options[axle+'_rate']
                    length=options[axle+'_length']
                    if length is not None:
                        span=math.dist(positions[nodes[0]],positions[nodes[1]])
                        if span<=1e-6:raise PatchError('Cannot set length of a zero-length spring.')
                        overrides['beamPrecompression']=length/1000/span
                elif options[axle+'_damping'] is not None:
                    # Preserve the original rebound value, including when it was
                    # implicitly inherited from beamDamp.
                    overrides['beamDamp']=options[axle+'_damping']
                    if 'beamDampRebound' not in props and 'beamDamp' in props:
                        overrides['beamDampRebound']=json.loads(doc.tokens[props['beamDamp']].value)
                if not overrides:continue
                existing=dict(doc.props(inline)) if inline is not None else {}
                added={}
                for key,value in overrides.items():
                    if key in existing:changes.append((*doc.span(existing[key]),json.dumps(value)))
                    else:added[key]=value
                if added:
                    if inline is not None:
                        pos=doc.tokens[inline].end
                        changes.append((pos,pos,json.dumps(added)[1:-1]+','))
                    else:
                        pos=doc.tokens[doc.ends[row]].start
                        sep='' if doc.tokens[doc.ends[row]-1].value==',' else ','
                        changes.append((pos,pos,sep+json.dumps(added)))
        result[name]=edits(doc.text,changes).encode()
    return result
