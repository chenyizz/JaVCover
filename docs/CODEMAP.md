# JAVCover 当前项目 Codemap

本图谱对应当前 PySide6 桌面应用。应用离线处理图像；色块建议只是启发式候选，OCR 依赖用户本机的 Tesseract，PSD 导入受限且不是 Photoshop 插件。代码按分层与职责放入 `core/`、`services/`、`ui/`（含 `canvas/`、`widgets/`、`dialogs/`、`features/`）等分类包，彻底解耦。

## 目录结构

```text
src/javcover/
├── app.py                      # 入口：main() + _startup_path()
├── core/                       # 无 UI 的基础层
│   ├── errors.py               # ImageError
│   ├── tasks.py                # TaskCancelled
│   ├── constants.py            # 混合模式标签、图片后缀、format_output_name
│   ├── resources.py            # ICON_DIR（打包后仍指向包内 icons/）
│   ├── models.py               # Project / Region / DesignElement / Guide / Rect / snap_rect
│   └── crop.py                 # image_rect_mapping / crop_image_to_rect（返回 QImage）
├── services/                   # 服务层（可脱离界面使用）
│   ├── image_ops.py            # 图片读取、PNG 编解码、项目合成、区域/文字绘制
│   ├── assist.py               # 色块候选 + 可取消的 Tesseract OCR 适配
│   ├── psd_import.py           # 可选 psd-tools 导入 / 栅格化
│   ├── template_io.py          # .javcover v7 ZIP 持久化（读 v1–v7）
│   └── canvas_widgets.py       # 像素标尺、参考线拖入
├── icons/                      # 图标与许可证
└── ui/
    ├── main_window.py          # MainWindow 外壳（菜单、面板框架、窗口装饰）
    ├── editor_tab.py           # EditorTab：编辑标签页（控件条 + RulerFrame + ImageEditor + 坐标状态栏）
    ├── canvas/                 # 画布相关
    │   ├── scene.py            # CoverScene（网格、参考线跨视图、光盘/印刷叠加、裁剪预览）
    │   ├── items.py            # RegionItem / DesignElementItem
    │   ├── view.py             # CoverView（工具、拖拽、缩放、拖放）
    │   ├── crop.py             # CropOverlay（绘制）+ CropTool（画布裁剪状态机）
    │   ├── handles.py          # draw_handles / handle_points（圆形屏幕恒定选择手柄）
    │   └── image_editor.py     # ImageEditor（QGraphicsView：标尺/参考线/平移/裁剪/吸附/缩放）
    ├── widgets/                # 通用控件
    │   ├── panel.py            # PanelDock / PanelTitleBar（卡片模板）
    │   ├── flow_layout.py      # FlowLayout（自动折行）
    │   ├── scrub.py            # ScrubSpinBox（拖动改值）
    │   ├── controls.py         # 工具按钮反馈 / 窗口控制 / 延迟提示
    │   └── worker.py           # _BackgroundWorker（QThread，可取消）
    ├── dialogs/                # 对话框
    │   ├── preferences.py      # PreferencesDialog
    │   ├── text_element.py     # TextElementDialog
    │   └── new_canvas.py       # NewCanvasDialog + CANVAS_PRESETS
    └── features/               # MainWindow 功能混入（每个模块一个职责）
        ├── preferences.py      # 工具栏/工具面板/偏好/网格/吸附
        ├── project.py          # 新建/打开/保存/撤销/自动保存恢复
        ├── exporting.py        # 单张/CMYK/流水线批量导出
        ├── assets.py           # 素材库、拖放建层、素材刷新/重链接
        ├── assist.py           # 色块/OCR 分析与设置
        ├── editing.py          # 中央标签页（封面 + 图片/区域编辑标签），切换标签选中目标，应用裁剪/平移
        ├── regions.py          # 区域面板与操作
        ├── guides.py           # 参考线面板与操作
        └── elements.py         # 图层面板、文字/图片编辑、层级
```

测试与脚本：`tests/`（按模块命名）、`build.ps1`、`run_javcover.py`、`installer/JAVCover.iss`、`tools/make_icon.py`。

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m pyflakes src\javcover tests
```

## 分层与依赖方向（单向）

```text
core            （errors / tasks / constants / resources / models / crop —— 无 UI 依赖）
  ↑
services        （image_ops / assist / psd_import / template_io / canvas_widgets）
  ↑
ui.widgets / ui.canvas / ui.dialogs   （可复用控件与画布）
  ↑
ui.features.*   （MainWindow 功能混入）
  ↑
ui.main_window  （外壳组合）
  ↑
app.main
```

- 服务层不依赖任何界面状态；裁剪的**几何**在 `core/crop.py`，**绘制**在 `ui/canvas/crop.py:CropOverlay`，**交互状态机**在 `CropTool`，文档数据只在应用裁剪时改动。
- `MainWindow` 由 `ui/features/*` 混入组合；每个 feature 只负责一类行为。

## 主要符号与职责

- `core/models.py`：`Rect`、`Region`、`DesignElement`、`Guide(axis, position, name)`、`Project(width, height, base_png, regions, guides, elements, shape)`、`snap_rect(...)`。
- `core/crop.py`：`image_rect_mapping`、`crop_image_to_rect`。
- `services/image_ops.py`：`load_image`、`encode_png`/`decode_png`、`composition_mode`、`paint_region_background`、`build_text_path`/`paint_text_element`、`compose_project`（`shape=="disc"` 裁圆）。
- `services/assist.py`：`suggest_color_blocks`、`recognize_japanese_text(..., cancel_event)`、`list_tesseract_languages`、`resolve_tesseract`。
- `services/psd_import.py`：`import_psd`、`rasterize_psd`、`import_psd_overlay`。
- `services/template_io.py`：`save_project` / `load_project`，`FORMAT_VERSION = 7`，读 v1–v7。
- `ui/canvas/scene.py` / `items.py` / `view.py` / `crop.py` / `handles.py` / `image_editor.py`：场景、图元、交互视图、画布裁剪工具、共享选择手柄、非模态图片编辑器（QGraphicsView）。
- `ui/editor_tab.py` / `ui/features/editing.py`：中央标签页系统——封面画布为标签 0，双击图片图层/区域背景打开“编辑”标签（可切换、非模态），`EditorTab` 用 `RulerFrame` 提供标尺/参考线并显示光标坐标与选区尺寸；切换标签会选中对应区域/图层使右侧卡片动态显示；`ImageEditor` 支持平移/裁剪/吸附/滚轮缩放/中右键平移；应用时写回并关闭标签。
- `ui/widgets/*`、`ui/dialogs/*`：通用控件与对话框（见目录树）。
- `ui/features/*`：见目录树。

## 目前未覆盖

- 色块建议不理解封面语义，也不提供置信度/模型分割。
- OCR 需用户安装 Tesseract 与 `jpn` 数据并人工校对。
- PSD 文字编辑仍需在 Photoshop 完成；标题素材为不可拆分的栅格图层。
- 设计图层尚无排序之外的锁/混合之外的图层属性；批量导出命名占位符有限；印刷仅 ICC 嵌入，无 CMYK 之外的完整色彩管理。
- 安装包尚未在干净 Windows 环境实测。
