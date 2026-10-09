-- BeamNG reloads extensions with Ctrl+L. Avoid unloading inside mod-script
-- initialization, where its compatibility loader wraps extensions.load.
if not extensions.mininiDebug then extensions.load('mininiDebug') end
setExtensionUnloadMode('mininiDebug', 'manual')
