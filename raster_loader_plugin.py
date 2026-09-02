# -*- coding: utf-8 -*-
import os
from qgis.PyQt.QtWidgets import QAction
from qgis.PyQt.QtGui import QIcon
from qgis.core import QgsApplication
from .raster_loader_dialog import RasterLoaderDialog


class RasterLoaderPlugin:
    def __init__(self, iface):
        self.iface = iface
        self.plugin_dir = os.path.dirname(__file__)
        self.action = None
        self.dialog = None

    def initGui(self):
        icon_path = os.path.join(self.plugin_dir, 'icon.png')
        icon = QIcon(icon_path) if os.path.exists(icon_path) else \
               QgsApplication.getThemeIcon('/mActionAddRasterLayer.svg')

        self.action = QAction(icon, 'Raster Loader', self.iface.mainWindow())
        self.action.setToolTip('ポリゴン範囲のラスタを一括読み込み')
        self.action.triggered.connect(self.run)
        self.iface.addToolBarIcon(self.action)
        self.iface.addPluginToRasterMenu('Raster Loader', self.action)

    def unload(self):
        self.iface.removePluginRasterMenu('Raster Loader', self.action)
        self.iface.removeToolBarIcon(self.action)
        del self.action

    def run(self):
        if self.dialog is None:
            self.dialog = RasterLoaderDialog(self.iface)
        self.dialog.refresh_layers()
        self.dialog.show()
        self.dialog.raise_()
        self.dialog.activateWindow()
