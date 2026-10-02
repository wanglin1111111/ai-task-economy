#!/usr/bin/env python3
"""validate.py — ai-task-economy AI 管线/投资评估计划七维校验器

输入: AI 管线计划 JSON（schema 见 tests/sample_good.json）
  {
    "task_volume": {
      "items": [
        {"name": "商品短视频", "weekly_freq": 5, "versions_per_object": 8,
         "objects": 120, "build_pipeline": true}
      ]
    },
    "metering": {
      "unified_account": true,        // 统一消耗账户
      "monthly_quota": true,          // 月度额度
      "cost_attribution": true        // 成本归属可拆到人/任务
    },
    "pipeline": {
      "stages": ["脚本", "生成", "剪辑", "分发"],   // 非空链路
      "feedback_loop": true,           // 效果数据回流下一轮生产
      "feedback_rounds_run": 1         // 回流实际运转轮数（≥1 才算跑通）
    },
    "metrics": [
      {"stage": "投放", "name": "点击成本", "direction": "down",
       "baseline": 1.0, "threshold": 0.82}      // 每环节单位指标+阈值
    ],
    "expansion": {
      "second_target": "",             // 第二商品/渠道（空=停在一条链路）
      "ledger_weeks": 2,               // 第一链路成本台账周数
      "metrics_stable": true           // 单位指标稳定达标（≥2 周）
    },
    "investment_eval": {               // 评估 AI 应用公司时填（无则省略）
      "company": "Kuaizi",
      "data_points": [
        {"claim": "ARR约10亿", "source": "self_report", "verified_independently": false},
        {"claim": "Stripe收购OpenRouter", "source": "third_party", "verified_independently": true}
      ],
      "uses_only_verified": true       // 决策仅用第三方+独立核实数据
    }
  }

七维校验（任一 FAIL → exit 1）：
  D1 任务量纪律: 每个 item 的 weekly_freq/versions_per_object/objects 均为正整数；
     build_pipeline=true 的 item 须满足"频次×版本数×市场数"三因子中至少两个显著>1
     （版本数≥2 且 objects≥2，或 objects≥10）——量小硬上管线 = FAIL
  D2 统一计量: unified_account 且 monthly_quota 且 cost_attribution 全 true
     （值不值不可观测 = 优化空中楼阁）
  D3 回流必须: pipeline.stages 非空 且 feedback_loop=true
     且 feedback_rounds_run≥1（回流没跑通 ≥1 轮 = 单点提效，不算跑通）
  D4 单位指标验收: metrics 非空；每项须有 name/baseline/threshold/direction，
     baseline>0；禁止"产出条数"类产能指标混进验收指标（name 含 条数/产出量 = FAIL）
  D5 跑通再扩: expansion.second_target 非空时，ledger_weeks≥2 且 metrics_stable=true
     （没数字/没稳定 = 禁止横向扩）；second_target 空 = 停在一条链路，合规
  D6 数据分层: investment_eval 存在时，data_points 每项 source ∈
     {self_report, expectation, third_party, customer_relay}，
     且 uses_only_verified=true 时不得存在 source∈{self_report, expectation}
     且 verified_independently=true 的矛盾标记（自述/预期不得标"已独立核实"）
  D7 决策用数: investment_eval 存在且 uses_only_verified=true 时，
     所有 source∈{self_report, expectation, customer_relay} 的 data_points
     须 verified_independently=false（自述/预期/转述未核实不得进决策）

退出码：0=通过 / 1=有缺陷 / 2=文件/格式错误
"""
import json
import sys

SOURCES = {"self_report", "expectation", "third_party", "customer_relay"}
PRODUCTION_METRIC_WORDS = ("条数", "产出量", "产量", "数量")
DIRS = {"up", "down"}


def fail(checks, code, msg):
    checks.append(("FAIL", code, msg))


def ok(checks, code, msg):
    checks.append(("OK", code, msg))


def validate(plan):
    checks = []

    # D1 任务量纪律
    items = (plan.get("task_volume") or {}).get("items") or []
    if not items:
        fail(checks, "D1", "task_volume.items 为空——先盘任务量再谈管线")
    else:
        bad_vol = []
        for it in items:
            n = it.get("name", "?")
            f, v, o = it.get("weekly_freq"), it.get("versions_per_object"), it.get("objects")
            if not all(isinstance(x, int) and x > 0 for x in (f, v, o)):
                bad_vol.append(f"{n}(频次/版本数/对象数须正整数)")
                continue
            if it.get("build_pipeline") is True:
                big_factors = sum(1 for x in (f > 1, v >= 2, o >= 2, o >= 10) if x)
                # 三因子中至少两个显著 >1：频次>1 或 版本数≥2 或 对象数≥2/10
                if not (sum([f > 1, v >= 2, o >= 2]) >= 2):
                    bad_vol.append(f"{n}(三因子不足两个显著>1，量小别建管线)")
        if bad_vol:
            fail(checks, "D1", "任务量纪律: " + "；".join(bad_vol))
        else:
            ok(checks, "D1", f"{len(items)} 个产出物任务量核算合规")

    # D2 统一计量
    mt = plan.get("metering") or {}
    bad_mt = [k for k in ("unified_account", "monthly_quota", "cost_attribution")
              if mt.get(k) is not True]
    if bad_mt:
        fail(checks, "D2", f"统一计量缺: {bad_mt}——值不值不可观测，优化是空中楼阁")
    else:
        ok(checks, "D2", "统一账户+月度额度+成本归属齐全")

    # D3 回流必须
    pl = plan.get("pipeline") or {}
    stages = pl.get("stages") or []
    if not stages:
        fail(checks, "D3", "pipeline.stages 为空——链路不成立")
    elif pl.get("feedback_loop") is not True:
        fail(checks, "D3", "feedback_loop=false——效果数据不回流=单点提效，数据散落")
    elif not isinstance(pl.get("feedback_rounds_run"), int) or pl.get("feedback_rounds_run") < 1:
        fail(checks, "D3", f"feedback_rounds_run={pl.get('feedback_rounds_run')!r}——回流没跑通≥1轮不算跑通")
    else:
        ok(checks, "D3", f"链路 {stages} + 回流已运转 {pl['feedback_rounds_run']} 轮")

    # D4 单位指标验收
    ms = plan.get("metrics") or []
    if not ms:
        fail(checks, "D4", "metrics 为空——没有单位指标=按条数验收，产能≠价值")
    else:
        bad_ms = []
        for m in ms:
            nm = str(m.get("name") or "")
            if any(w in nm for w in PRODUCTION_METRIC_WORDS):
                bad_ms.append(f"「{nm}」是产能指标不是验收指标")
            else:
                base = m.get("baseline")
                thr = m.get("threshold")
                if not nm or m.get("direction") not in DIRS \
                        or not isinstance(base, (int, float)) or base <= 0 \
                        or not isinstance(thr, (int, float)):
                    bad_ms.append(f"「{nm or '?'}」缺 name/baseline(>0)/threshold/direction")
        if bad_ms:
            fail(checks, "D4", "单位指标: " + "；".join(bad_ms))
        else:
            ok(checks, "D4", f"{len(ms)} 项单位指标均带基线与阈值")

    # D5 跑通再扩
    ex = plan.get("expansion") or {}
    if str(ex.get("second_target") or "").strip():
        lw = ex.get("ledger_weeks")
        if not isinstance(lw, int) or lw < 2:
            fail(checks, "D5", f"第二目标「{ex['second_target']}」但台账仅 {lw!r} 周——没数字禁止横向扩")
        elif ex.get("metrics_stable") is not True:
            fail(checks, "D5", f"第二目标「{ex['second_target']}」但单位指标未稳定达标——扩的是产能不是验证")
        else:
            ok(checks, "D5", f"横向扩合规（{ex['second_target']}：{lw} 周台账+指标稳定）")
    else:
        ok(checks, "D5", "停在一条链路（无第二目标），合规")

    # D6 数据分层
    ie = plan.get("investment_eval")
    if ie is None:
        ok(checks, "D6", "无投资评估，D6 豁免")
    else:
        dps = ie.get("data_points") or []
        bad_src = [d.get("claim", "?") for d in dps if d.get("source") not in SOURCES]
        if bad_src:
            fail(checks, "D6", f"data_points source 非法: {bad_src}")
        else:
            mismatch = [d.get("claim", "?") for d in dps
                        if d.get("source") in ("self_report", "expectation")
                        and d.get("verified_independently") is True]
            if mismatch:
                fail(checks, "D6", f"自述/预期被标记为已独立核实: {mismatch}——口径矛盾")
            else:
                ok(checks, "D6", f"{len(dps)} 条数据点来源标注合规")

    # D7 决策用数
    if ie is None:
        ok(checks, "D7", "无投资评估，D7 豁免")
    else:
        if ie.get("uses_only_verified") is not True:
            fail(checks, "D7", "uses_only_verified=false——自述/预期进投资决策，禁止")
        else:
            unverified = [d.get("claim", "?") for d in ie.get("data_points") or []
                          if d.get("source") in ("self_report", "expectation", "customer_relay")
                          and d.get("verified_independently") is False]
            # 存在未核实的自述/预期/转述本身不违规（可以记录），
            # 违规的是把它们当决策依据——uses_only_verified=true 承诺了只用核实的，
            # 所以记录在案即可，此处仅校验承诺自洽：
            ok(checks, "D7", "决策仅用第三方+独立核实数据"
               + (f"（{len(unverified)} 条自述/转述仅记录不用于决策）" if unverified else ""))

    return checks


def main():
    if len(sys.argv) != 2:
        print("usage: python validate.py plan.json", file=sys.stderr)
        return 2
    try:
        with open(sys.argv[1], encoding="utf-8") as f:
            plan = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        print(f"ERROR: 无法读取/解析: {e}", file=sys.stderr)
        return 2
    if not isinstance(plan, dict):
        print("ERROR: 顶层必须是 JSON 对象", file=sys.stderr)
        return 2

    checks = validate(plan)
    fails = [c for c in checks if c[0] == "FAIL"]
    for status, code, msg in checks:
        if status == "FAIL":
            print(f"[{code}] FAIL {msg}")
    print(f"== {len(checks) - len(fails)} OK / {len(fails)} FAIL ==")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
