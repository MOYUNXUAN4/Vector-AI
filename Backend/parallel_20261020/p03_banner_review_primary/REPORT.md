# P03 无实验横幅：共享层数适用域拒绝

2026-10-20。只读诊断，没有修改Unity、游戏包、后端运行代码、模型、阈值、原数据或预检锁；没有启动服务或模型。

## 结论

不是已发现的启动器误用，也不是新统一UI导致。独立游戏支持5层，但当前后端共享归一化器只把3、8、10层视为可用游戏阶段。P03六局均为5层，因而整局被拒绝为 `unsupported_or_calibration_phase`。

主代理此前确认5层时只检查了Player菜单与归一化常量，没有检查后端共享适用域，这是准备检查遗漏。静态哈希一致并不能证明所选配置具有端到端兼容性。

## 精确依据

- 用户确认使用 `Start_Pilot_10P_Experimental.cmd`；20:40:27有对应静态通过回执 `preflight_e1f94ec18f3643aa9a1217c5c9fd38c6.json`。回执不单独证明整个服务运行成功，但与本次用户确认一致。
- 桌面快捷方式指向既有正常独立包 `6F1E9B5F-1F20-4BB7-BCB4-6E8B23795054/VectorAI.exe`，Player.log首行Mono路径一致；六条start_session明确为P03且run与CSV匹配。
- 六局CSV合计11,586个Unity源包，难度3、selected_session_layers=5。四局完成、两局坠出，均保留。用户确认原黄色／attention正常，仅三个实验横幅没有出现。
- 按六个精确run匹配到11,580条TTE影子记录，全部 `active=false`、`causal_available=false`，原因全部为 `unsupported_or_calibration_phase`。没有用整个共享文件推断P03。
- Player.log中三种Experimental警告标签计数均为0；这支持未见客户端激活证据，但本身不能替代屏幕像素证明。

## 代码与最小复现

`parallel_20261010/backend/runtime_adapter.py` 中 `normalize_unity_packet` 的 `gameplay_phase_valid` 使用：

```python
selected in (3, 8, 10)
```

不满足时把方向有效性置false并返回 `unsupported_or_calibration_phase`。LightGBM运行时、GeometryDanger和TTE影子均使用这个共享归一化器；因此不是只有紫色显示开关的问题。`calibration_mode=true`在这里是配置式采集模式，不能解读成用户整局停在准备界面。

主代理用同一个无网络、无模型的合成有效packet，只切换 `selected_session_layers`：

| 层数 | gameplay_phase_valid | 归一化原因 |
|---|---|---|
| 3 | true | 无拒绝原因 |
| 5 | false | unsupported_or_calibration_phase |
| 8 | true | 无拒绝原因 |
| 10 | true | 无拒绝原因 |

即使几何有效、run正在运行、平台身份准确，5层仍被拒绝。现有证据足以解释本次实验预警不可用，不需要通过降低报警阈值或延长显示来修。

## P03 数据处理

保留全部原始数据。登记为“用户未观察到实验横幅，后端实验路径全程不适用”，不能归入实验提示已实际启用且有效的组；也不能直接称为随机分配的无提示对照组。它仍可用于运动/任务与系统兼容性分析，具体可评价区间另做QC。不得将本次不可用输出当成模型有效预测下的普通漏检，也不得从整体系统覆盖中抹掉这6局。

## 建议的修复与验证（尚未执行）

若继续固定5层，最小改动是在共享适用域明确增加5层，而不是关闭身份/时钟/几何有效性检查。需验证原3、8、10层行为不变，5层正常阶段可用，真正校准/无效几何/断流仍拒绝；该兼容扩展不等于模型性能通过。

通过测试后，只更新经审查的对应预检哈希，不绕过预检、不整体重置锁。Unity及当前独立包无需因这项后端兼容性修改而重打包。随后用单独操作员账号做一局靠边回正检查，核对后台可用状态、客户端激活与实际来源显示，再继续同条件集采。

机械证据、逐局统计和输入SHA前后记录见 `../p03_banner_review_luna/REPORT.md` 与 `input_sha256.json`。本报告没有重训、离线改标签或将P03自动加入训练集。
