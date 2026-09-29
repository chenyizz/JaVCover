# JAVCover 当前项目 Codemap

本图谱对应当前 PySide6 桌面原型。应用离线处理图像；色块建议只是启发式候选，OCR 依赖用户本机的 Tesseract，PSD 导入受限且不是 Photoshop 插件。

## 目录结构

```text
JAVCover/
├── .vscode/
│   ├── launch.json
│   └── settings.json
├── docs/
│   ├── CODEMAP.md
│   ├── DEVELOPMENT.md
│   ├── PROJECT_PLAN.md
│   ├── STATE.md
│   └── THIRD_PARTY_NOTICES.md
├── installer/
│   └── JAVCover.iss            # Inno Setup 安装程序脚本
├── tools/
│   └── make_icon.py            # 由 app-icon.svg 生成多尺寸 .ico
├── src/javcover/
│   ├── app.py                  # 入口 main() 与公共符号再导出（兼容旧导入）
│   ├── constants.py            # 混合模式标签、图片后缀、批量文件名格式化
│   ├── resources.py            # 图标目录定位（打包后仍指向包内 icons/）
│   ├── tasks.py                # TaskCancelled 取消异常
│   ├── assist.py               # 大色块候选与 Tesseract 日文 OCR 适配
│   ├── canvas_widgets.py       # 像素标尺、参考线拖入
│   ├── image_ops.py            # 图片读取、PNG 编码、项目图层合成
│   ├── icons/                  # 工具图标、app-icon.svg 应用图标及许可证
│   ├── models.py               # Project、Region、DesignElement、Guide、Rect
│   ├── psd_import.py            # 可选 psd-tools PSD 导入适配器
│   ├── template_io.py          # .javcover v6 ZIP 持久化、v1–v5 读取兼容
│   └── ui/
│       ├── __init__.py
│       ├── canvas.py           # CoverScene / RegionItem / DesignElementItem / CoverView
│       ├── dialogs.py          # PreferencesDialog / TextElementDialog / NewCanvasDialog
│       ├── flow_layout.py      # FlowLayout（工具面板自动折行）
│       ├── image_edit.py       # ImageEditDialog（平移/裁剪专用编辑窗口）
│       ├── main_window.py      # MainWindow（菜单、面板、项目读写、批量等）
│       ├── panel.py            # PanelDock / PanelTitleBar（统一卡片模板）
│       ├── scrub.py            # ScrubSpinBox（可拖动改值）
│       ├── widgets.py          # _ToolButtonFeedback / _WindowControlButton / _DelayedToolTip
│       └── worker.py           # _BackgroundWorker（QThread，可取消）
├── tests/
│   ├── test_app_ui.py
│   ├── test_assist.py
│   ├── test_canvas.py
│   ├── test_image_ops.py
│   ├── test_models.py
│   ├── test_psd_import.py
│   ├── test_rulers.py
│   └── test_template_io.py
├── build.ps1                   # 发布构建：单文件/目录版/便携 zip
├── run_javcover.py             # 冻结应用入口（保持包内资源路径）
├── pyproject.toml              # 运行依赖与 psd 可选依赖
├── README.md
└── AGENTS.md
```

`.venv/` 是本地 Python 虚拟环境，不是源码。测试使用项目虚拟环境：

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

## 模块关系

```text
用户
 └─ app.py: main()
     └─ MainWindow
         ├─ 紧凑菜单行: 菜单、应用图标位及窗口控制按钮
         ├─ 左侧工具栏: 单色 IconPark 图标、延迟提示与按钮动效
         ├─ CoverView (QGraphicsView)
         │   ├─ CoverScene: 网格和参考线
         │   ├─ RegionItem / DesignElementItem
         │   └─ models.py: 项目数据与坐标
         ├─ assist.py: 本地 OCR 与色块候选
         ├─ psd_import.py: 可选 PSD 导入
         ├─ image_ops.py: 解码/编码/合成
         ├─ template_io.py: 模板校验/持久化
         └─ QSettings: 画布偏好、窗口几何、面板/卡片布局

tests/
 ├─ test_assist.py ────────────── assist.py
 ├─ test_canvas.py ────────────── app.py + models.py
 ├─ test_image_ops.py ─────────── image_ops.py + models.py
 ├─ test_models.py ────────────── models.py
 ├─ test_psd_import.py ────────── psd_import.py
 ├─ test_rulers.py ────────────── canvas_widgets.py + app.py
 └─ test_template_io.py ───────── template_io.py + models.py
```

`models.py` 保持数据模型职责；服务模块不依赖界面状态，鼠标交互和用户确认留在 `app.py`。识别只产生可修改的候选框，不静默覆盖已有编辑。

## 主要符号与职责

### `src/javcover/models.py`

- `Rect`：源图像像素坐标整数矩形、边界裁切（`bounded`）与限制在外层矩形内（`bounded_within`，供关联区域图层使用）、拖拽坐标归一化。
- `Region`：有稳定 ID、名称、矩形、可选区域背景 PNG、`locked`/`visible` 状态、`opacity`（0–100）、背景 `fit`（`cover`/`contain`/`stretch`）、`blend_mode` 与背景平移 `bg_dx`/`bg_dy`。
- `DesignElement`：内嵌 PNG 图片或文字内容，以及像素坐标和基础文字样式；含 `locked`/`visible`/`opacity`/`blend_mode` 与可选 `region_id`（关联区域，元素被限制在该区域矩形内）；图片可携带 `asset_name`/`asset_kind`/`asset_hash`，记录来源素材以便刷新。
- `Guide`：垂直 `x` 或水平 `y` 参考线，带可选 `name` 名称。
- `Project`：画布尺寸与形状（`shape`：`rect`/`disc`）、底图、区域、参考线和设计图层。
- `snap_rect(...)`：吸附到画布边、参考线、邻区边/中心或网格。

### `src/javcover/ui/`（原 app.py 拆分）

- `ui/canvas.py`：`CoverScene`、`RegionItem`、`DesignElementItem`、`CoverView`。
- `ui/dialogs.py`：`PreferencesDialog`、`TextElementDialog`。
- `ui/widgets.py`：`_ToolButtonFeedback`、`_WindowControlButton`、`_DelayedToolTip`。
- `ui/worker.py`：`_BackgroundWorker`。
- `ui/scrub.py`：`ScrubSpinBox`（拖动框体改值的数字框，供不透明度/网格/尺寸等复用）。
- `ui/image_edit.py`：`ImageEditDialog`——双击区域/图层打开，平移图片、可拖边/角裁剪（框外虚化 + 对齐网格），Enter 应用。`_Preview` 负责绘制与交互。
- `ui/flow_layout.py`：`FlowLayout`——按宽度自动折行的布局，用于工具面板（窄时单列、拉宽时多列）。
- `ui/panel.py`：`PanelDock` / `PanelTitleBar`——**所有卡片（工具/区域/参考线/图层）的统一模板**：始终保留 `windowTitle`（供标签页与“视图”菜单显示名称）、紧凑标题栏只显示名称（无 x/口 按钮）、`Movable|Floatable` 且可停靠任意区域；工具面板是本模板的“内容为流式工具按钮”的子集。`_new_inspector_card` 与 `_create_tool_rail` 都基于它，避免各面板被反复单独打补丁。
- `ui/main_window.py`：`MainWindow`（下列符号除特别注明外均在此文件）。
- `app.py`：仅保留 `main()`、`_startup_path()` 并再导出 `MainWindow`/`CoverView`/`CoverScene`/`RegionItem`/`DesignElementItem`/`PreferencesDialog`/`TextElementDialog`/`format_output_name` 以兼容旧导入。

以下符号按上述文件分布：

- `CoverScene`：前景网格、参考线、参考线拖动预览，以及可选的印刷参考线（出血/安全区）叠加。参考线绘制跨越整个可见视图（不裁剪到画布），始终延伸到标尺边缘。
- `RegionItem` / `DesignElementItem`：区域和图层预览、边框、选中控制点；均可按 `opacity`、`blend_mode` 绘制、按 `visible` 隐藏，`locked` 时只显示灰色虚线框不显示手柄。文字预览调用 `image_ops.paint_text_element`，区域背景调用 `paint_region_background`，与导出使用同一渲染路径。区域名标签只在选中或悬停时显示并裁剪在区域矩形内，避免色块候选框名称重影。选中区域为黑色描边 + 黄色实线 + 半透明填充，选中图层为黑色描边 + 亮青实线，便于与 1px 网格区分。
- `main()`：启动时安装 `qtbase_zh_CN` QTranslator，使标准对话框按钮（保存/放弃/取消/确定等）本地化为中文。
- `CoverView`：左键选框/对象移动与八向调整（角手柄按住 Shift 等比缩放）、右键/中键平移、滚轮缩放（缩放修饰键由 `wheel_zoom_modifier` 控制：none/ctrl/alt/shift/disabled）、参考线操作；`crop_mode` 下拖动裁剪图片图层/区域背景，Ctrl+拖动平移区域背景（`_begin_crop`/`_apply_crop`/`bgpan`）；接受图片/PSD 拖放并发 `filesDropped`；`set_project(preserve_view=True)` 供撤销/重做保留视图；`_constrain_element_rect` / `reclamp_linked_elements` 把关联区域的图层限制在区域内；`_align_rect` / `set_alignment_guides` 在移动时向画布/区域/其它图层中心与边缘吸附并显示紫色对齐线。手柄按屏幕像素固定大小绘制，避免放缩后难点中。锁定区域/图层不出手柄、不响应移动/缩放。使用 `FullViewportUpdate` 避免增删候选框时的残影。
- `_startup_path` / `MainWindow.open_path`：读取命令行/拖到 exe 传入的 `.javcover` 或图片路径并打开（配合安装脚本的可选文件关联）。
- `_BackgroundWorker` / `MainWindow._run_background`：以 `QThread` + 模态 `QProgressDialog`（带“取消”）执行 OCR、PSD 导入、导出、CMYK、批量；work 回调接收 `threading.Event`，置位后协作者抛 `TaskCancelled`；OCR 用 `Popen` 轮询并终止子进程。进行中禁止关闭主窗口。
- `_apply_ocr_candidates`：在 UI 线程裁剪 OCR 候选为画布内区域并建立候选框。
- `_analysis_image`：色块/OCR 分析改用 `compose_project` 合成图（底图 + 可见区域背景），因此打开只含区域背景的模板后仍可重新划分区域。
- `TextElementDialog`：系统字体选择及文字内容、字号、填充/描边、竖排等设置。
- `MainWindow`：紧凑菜单行与窗口控制、左侧单色 IconPark 工具轨、右侧三个可停靠/浮动/关闭的面板（区域/参考线/图层）、项目读写、撤销/重做、素材库和 OCR 配置；区域/图层列表支持锁定/显隐并更新画布命中状态。“设置 → 偏好设置”管理工作区选项及快捷键，均通过 `QSettings` 保存。全屏时菜单行不启动窗口移动。
- `place_psd_title_asset` / `refresh_selected_asset` / `relink_selected_asset`：PSD 标题素材的放置、从素材库刷新、重新链接；`_place_asset` 会为库内素材记录 `asset_name`/`asset_kind`/`asset_hash`。素材库（`open_asset_library`）支持分类子文件夹、导入文件/文件夹、平铺图标浏览、删除与双击放入；`_asset_path_for` 递归查找素材。
- `_toggle_region_locked` / `_toggle_region_visible` / `_region_fit_changed` / `_region_opacity_changed`：区域锁定、显隐、背景填充方式与不透明度。
- `_toggle_element_locked` / `_toggle_element_visible` / `_element_opacity_changed` / `move_selected_element` / `duplicate_selected_element`：图层锁定、显隐、不透明度、上下移层与复制。
- `_default_export_path` / `_render_export` / `_render_batch_stem` / `batch_export`：导出默认命名与上次目录、单张渲染、流水线批量生成（多目标区域各选素材文件夹，按文件名 stem 对应组合、可用前缀/后缀）。
- `_on_files_dropped` / `_build_image_element`：把拖入的图片/PSD 建成图层；落在区域上则关联该区域并缩放到区域内，落在空白则成为自由图层。
- `_autosave` / `_offer_recovery` / `_clear_recovery` / `_update_recovery_path`：编辑后延迟自动保存到 `recovery/directory`（默认 `AppLocalDataLocation`）下的 `recovery.javcover`，启动时若发现上次未正常退出则提示恢复；干净保存/退出会清除。仅在默认设置（真实运行）时启用，测试注入 QSettings 时关闭。
- `duplicate_selected_region` / `_rename_region_from_list`：复制区域（新 id、偏移、选中）、双击列表重命名区域。
- `_apply_icc_profile`：导出时（若设置了 `export/iccProfile`）用 `QColorSpace.fromIccProfile` 给图像附加颜色空间。
- `export_cmyk` / `_render_cmyk`：用 Pillow 将合成图转 CMYK（可选 `export/cmykProfile` 经 ImageCms 转换并嵌入），保存 TIFF/JPEG；Pillow 缺失时提示 `.[cmyk]`。
- `_create_toolbar` / `_create_tool_rail`：工具条引用与 `toggleViewAction` 加入“视图”菜单；`_create_tool_rail` 现构建**单列紧凑的可停靠/浮动“工具”卡片面板**（选择/框选/裁剪/色块/OCR/文字/素材）；`_restore_user_interface_state` 启动时强制显示被旧布局隐藏的工具条。
- `edit_selected_image` / `_on_edit_requested`：双击画布图片图层/区域背景或按 `E` 打开 `ImageEditDialog`，应用平移偏移或裁剪结果。
- `_refresh_region_list` / `_refresh_element_list`：重建列表时保留滚动条位置，锁定/显隐后不跳回。
- `format_output_name`：批量导出文件名占位符 `{name}` / `{index}` / `{date}` 展开。
- `PreferencesDialog`：提供常规选项和可配置 QAction 快捷键，检测重复键位并支持清空/恢复默认。`NewCanvasDialog`：常规/光盘画布预设与自定义宽高、形状。`TextElementDialog`：文字图层设置。
- `_new_inspector_card` / `_bind_panel_action`：将区域、参考线、图层各自建成独立 `QDockWidget`（可停靠任意边、浮动、关闭、嵌套/标签），内部为竖向 `QSplitter`（上半为控件 `QScrollArea` 区、下半为列表，可拖动改变列表高度）；对应“视图”菜单动作与面板可见性双向同步，布局由 `QMainWindow.saveState`/`restoreState` 持久化。
- `_refresh_region_list` / `_refresh_element_list`：列表项文本留空、名称只由行内 `QLabel` 显示，避免列表文字重影；行内含锁定/显隐按钮。
- `_ToolButtonFeedback`：工具按钮悬停/选中时以短时阴影动画显示状态。
- `_WindowControlButton`：按最小化、最大化/还原、全屏/退出全屏和关闭状态加载 `icons/window-*.svg`，不通过代码绘制图形。
- `_DelayedToolTip`：工具按钮悬停约 1.8 秒后再显示说明。

### `src/javcover/assist.py` 与 `psd_import.py`

- `suggest_color_blocks(...)`：在小型本地预览中检测全图水平/垂直的显著颜色跃变，最多给出矩形候选；这不是封面/脊柱/封底语义识别。
- `recognize_japanese_text(...)`：本机检查 Tesseract 可执行程序和 `jpn`/`eng` 模型后，以 `jpn+eng` TSV 输出文字框和候选内容；不联网。
- `list_tesseract_languages(...)`：通过本机 `--list-langs` 检查语言数据；允许使用单独指定的 tessdata 目录。
- `import_psd(...)`：可选 `psd-tools` 导入；隐藏可见 TypeLayer 以形成可替换文字的干净底图，并提取文字、边界与首段字体/字号/颜色/粗斜体/竖排样式。
- `rasterize_psd(...)`：将任意尺寸/透明度 PSD 复合结果栅格化为 `QImage`，供“PSD 标题素材”放置与刷新；不做同尺寸或透明背景限制。
- `import_psd_overlay(...)`：将 PSD 可见复合结果作为带透明度的栅格图像图层返回；仍要求有透明区域（保留给旧叠加语义/测试）。

### `src/javcover/image_ops.py`

- `load_image(...)`：读取本地图片并限制最多 1 亿像素。
- `encode_png(...)` / `decode_png(...)`：内存 PNG 资源转换/验证。
- `build_text_path(...)` / `paint_text_element(...)`：按设定字号构建文字路径并居中裁剪绘制，供画布预览与导出共用，含描边。
- `composition_mode(...)`：混合模式名（normal/multiply/screen/overlay/darken/lighten/add）到 `QPainter.CompositionMode` 的映射，供区域背景与图层绘制共用。
- `paint_region_background(...)`：按区域 `fit`（cover/contain/stretch）、`opacity`、`blend_mode` 与 `bg_dx/bg_dy` 偏移绘制区域背景，供画布与导出共用。
- `image_rect_mapping(...)` / `crop_image_to_rect(...)`：计算图片在目标矩形内的绘制/源矩形映射（支持 `offset` 平移），并按场景矩形裁剪图片（返回新 PNG 与新矩形），供裁剪工具与编辑窗口使用。
- `compose_project(...)`：依序合成底图、可见区域背景、可见图片元素和文字元素；隐藏区域背景与隐藏图层都会从导出中排除，区域/图层按各自不透明度与混合模式绘制。`shape == "disc"` 时用 `CompositionMode_Clear` 清除圆外区域。文字使用当前安装字体、按设定字号在元素框内居中渲染并裁剪（不拉伸，与画布预览一致）；JPEG 由 UI 铺白底并按 `export/jpegQuality`（1–100，默认 95）保存。

### `src/javcover/template_io.py`

- `save_project(...)`：写入 ZIP：JSON 清单及自包含的底图、区域和图片图层资源。
- `load_project(...)`：验证版本、资源路径、尺寸、ID、颜色和字段。
- 当前写入 `FORMAT_VERSION = 7`，可读取版本 1–7；版本 1 无设计元素，版本 2 无素材来源字段，版本 3 无 `opacity`/`fit`/图层 `locked`/`visible`，版本 4 无 `blend_mode`，版本 5 无元素 `region_id`，版本 6 无画布 `shape` 与区域 `bg_dx`/`bg_dy`。区域 `locked`/`visible`/`opacity`/`fit`/`blend_mode` 与元素 `asset_*`/`locked`/`visible`/`opacity`/`blend_mode`/`region_id` 均为向后兼容可选字段。

## 主数据流

```text
打开图片/PSD
 → QImage + Project
 → CoverView 构建底图、区域和图层

OCR/色块工具
 → assist.py 本地分析
 → 候选 Region
 → 用户移动、缩放、重命名或撤销

文字/素材
 → DesignElement
 → 项目图层侧栏 + 画布预览
 → .javcover 自包含保存 / image_ops 合成导出

PSD 标题素材
 → 导入素材库（复制到本机 asset-library）
 → rasterize_psd 栅格化复合结果 + 记录 asset_name/kind/hash
 → 画布图片图层（栅格）
 → 在 Photoshop 改 PSD → “刷新所选素材”重新栅格化，位置/尺寸不变
```

画布坐标始终对应图像原始像素，不随视图缩放改变。右/中键拖动只改变视图平移；选框和元素坐标不会随之改变。框选过程中右键会清理未提交的临时选框，再进入画布平移。八个手柄分别约束其相对边或角，调整坐标限制在画布内。

窗口几何、主窗口面板布局（`saveState`）、当前工具及网格/吸附设置保存在本机 `QSettings`，与 `.javcover` 文档内容分离；区域候选锁定和显隐随 `.javcover` 项目保存。首次窗口显示后会重新执行一次适合窗口缩放。

应用图标使用 `src/javcover/icons/app-icon.svg`（256 × 256 viewBox），菜单图标容器不额外绘制底色。窗口控制 SVG 资源位于同一 `icons/` 目录，并由 `_WindowControlButton` 根据窗口状态加载；区域/图层行状态图标为 `lock-closed.svg`、`lock-open.svg`、`eye-visible.svg`、`eye-hidden.svg`。工作区画布外围颜色用 `canvas/pasteboardColor` 保存。区域、参考线、图层面板为独立 `QDockWidget`，内部各自 `QScrollArea` 滚动，布局随窗口状态持久化。

## 目前未覆盖

- 色块建议不理解封面区域语义，也不提供统计置信度/模型分割。
- OCR 需用户单独安装 Tesseract 与日文 `jpn` 数据并人工校对结果。
- OCR 配置在“工具 → OCR 设置”选择本机 `tesseract.exe` 和包含 `jpn.traineddata`/`eng.traineddata` 的目录并验证；配置存于本机用户设置。
- PSD 文字编辑仍需在 Photoshop 完成；标题素材会把 PSD 复合为不可拆分的图像图层，来源素材只用于“刷新/重新链接”，不支持写回 PSD。
- 尚无图层锁定/隐藏/排序、混合模式、弧形/阴影/渐变文字、自动保存、批量导出、印刷出血和 ICC 色彩管理。
- 当前是源码原型，Windows 安装包尚未构建验证。
