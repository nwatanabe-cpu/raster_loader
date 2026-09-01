# -*- coding: utf-8 -*-
def classFactory(iface):
    from .raster_loader_plugin import RasterLoaderPlugin
    return RasterLoaderPlugin(iface)
