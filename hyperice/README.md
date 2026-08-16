# Hyperice / Hypervolt 放松资料包

为"运动后如何用 Hypervolt 放松肌肉"需求建立，2026-08-16。

## 组成

- `videos/` —— Hyperice 官方教学视频（B 站官方账号「HYPERICE海博艾斯」，mid 519439096），
  共 31 个分 P、约 1GB、全部 ffprobe 校验可播放（720p h264/aac）：
  - 《Hypervolt筋膜枪使用教程》BV12E411K7E3，14 个分 P：初级课（办公/CrossFit/髋部/电竞）、
    高级课（腓肠肌/腘绳肌/后背/胸肌）、大师课（肩胛带/颈部/斜方肌）、
    原理篇（肌筋膜松解/激痛点/震动疗法医学原理）
  - 《震动轴&筋膜球使用教程 NASM》BV167411o725，17 个分 P：激活术 + 分部位松解
    （腘绳肌/股外侧肌/四头肌/臀屈肌/背阔肌/腰方肌/背上侧/上肢/足底筋膜等）
- `../app/static/hypervolt.html` —— 手搓蓝牙引导页：手机 Chrome 直连筋膜枪自动调档，
  按运动类型（骑行/跑步/上肢/下肢/全身）分步引导部位、按摩头、档位、时长。

## 手机使用（一次性设置）

1. Chrome 地址栏输入 `chrome://flags/#unsafely-treat-insecure-origin-as-secure`
2. 文本框填 `http://192.168.18.104:8000`，选 Enabled，重启 Chrome
3. 打开 `http://192.168.18.104:8000/static/hypervolt.html`（需本机健康服务在运行，书签 `healthboard://` 可拉起）
4. 首次连接填筋膜枪 MAC（会记住）

## 每日提醒

计划任务 `HealthAssistantPostWorkoutRelax` 每天 21:55 查当天 Strava 活动，
有运动则弹通知 + 生成 `output/recovery/<日期>_放松指导.md`，休息日静默。

## 安全口径

疼痛即停；只打肌肉，避开骨骼/关节/脊柱/颈前/膝周；每部位 ≤2 分钟缓慢移动；
右膝康复期避开右膝周围（2026-08-10 起就医观察期，遵医嘱）。
出处：Hyperice 官方使用指引 + ACSM 冷身原则 + Mayo Clinic 恢复指南。
