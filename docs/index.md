---
description: AgentDescent — a parallel, asynchronous framework for self-evolving agents. Evolve prompts, skills, programs and harnesses with measurable held-out gates.
---

<div class="experience" data-theme="dark">
  <nav class="exp-nav" aria-label="Main navigation">
    <a class="exp-brand" href="./"><span class="brand-mark">a<span>↘</span></span> agentdescent</a>
    <div class="exp-nav-links">
      <a class="nav-active" aria-current="page" href="./"><span data-lang="zh">概览</span><span data-lang="en" hidden>Overview</span></a>
      <a href="#control-plane"><span data-lang="zh">控制面</span><span data-lang="en" hidden>Control plane</span></a>
      <a href="docs/"><span data-lang="zh">文档</span><span data-lang="en" hidden>Docs</span></a>
      <a class="nav-github" href="https://github.com/Birfy/agentdescent">GitHub ↗</a>
      <span class="lang-switch" role="group" aria-label="Language"><button type="button" data-lang-btn="zh" aria-pressed="true">中</button><button type="button" data-lang-btn="en" aria-pressed="false">EN</button></span>
    </div>
    <details class="exp-mobile-menu"><summary>Menu <span>▾</span></summary><div>
      <a aria-current="page" href="./"><span data-lang="zh">概览</span><span data-lang="en" hidden>Overview</span></a>
      <a href="#control-plane"><span data-lang="zh">控制面</span><span data-lang="en" hidden>Control plane</span></a>
      <a href="docs/"><span data-lang="zh">文档</span><span data-lang="en" hidden>Docs</span></a>
      <a href="#demo" aria-label="Demo"><span data-lang="zh">演示</span><span data-lang="en" hidden>Demo</span></a>
      <a href="https://github.com/Birfy/agentdescent">GitHub ↗</a>
    </div></details>
  </nav>

  <main>
    <section class="exp-hero">
      <div class="hero-content">
        <div class="eyebrow"><span class="pulse-dot"></span> SELF-EVOLVING AGENTS · OPEN SOURCE</div>
        <h1><span data-lang="zh">让 Agent<br><em>自己变强。</em></span><span data-lang="en" hidden>Make agents<br><em>improve themselves.</em></span></h1>
        <p class="hero-lead"><span data-lang="zh">AgentDescent 是一个并行、异步的自进化框架。定义要进化的对象，运行任务，按 held-out 结果合并每一处改进。</span><span data-lang="en" hidden>AgentDescent is a parallel, asynchronous framework for self-evolving agents. Define the artifact, run tasks, and merge only changes that improve held-out evidence.</span></p>
        <div class="hero-ctas"><a class="exp-button primary" href="install/"><span data-lang="zh">快速开始</span><span data-lang="en" hidden>Get started</span> <span>↗</span></a><a class="exp-button ghost" href="docs/"><span data-lang="zh">阅读文档</span><span data-lang="en" hidden>Read the docs</span> <span>→</span></a></div>
        <div class="hero-command"><span>$</span><code tabindex="0">curl -fsSL https://raw.githubusercontent.com/Birfy/agentdescent/main/scripts/install.sh | bash</code><button class="exp-copy" data-copy="curl -fsSL https://raw.githubusercontent.com/Birfy/agentdescent/main/scripts/install.sh | bash">Copy</button></div>
        <div class="hero-stats"><div><b>23</b><span data-lang="zh">方法端口</span><span data-lang="en" hidden>METHOD PORTS</span></div><div><b>12</b><span data-lang="zh">预览 PR</span><span data-lang="en" hidden>PREVIEW PRS</span></div><div><b>1</b><span data-lang="zh">统一入口</span><span data-lang="en" hidden>ENTRY POINT</span></div><div><b>0</b><span data-lang="zh">模型调用即可预览</span><span data-lang="en" hidden>MODEL CALLS TO PREVIEW</span></div></div>
      </div>

      <div class="hud" aria-label="Example evolution run">
        <div class="hud-top"><span class="dots"><i></i><i></i><i></i></span><span class="url">agentdescent.hugoxk.online</span><span class="live"><span class="led"></span>LIVE</span></div>
        <div class="hud-tabs"><span class="on">EVOLVE</span><span>GATES</span><span>LEDGER</span></div>
        <div class="term">
          <div class="ln"><span class="t">plan</span><span class="tag p">[ARTIFACT]</span><span class="txt">skill_dir · 18 tasks · 4 workers</span></div>
          <div class="ln"><span class="t">run</span><span class="tag c">[WORKER]</span><span class="txt">propose · diff touches 2 slots</span></div>
          <div class="ln"><span class="t">gate</span><span class="tag l">[LEAKAGE]</span><span class="txt">screen · no gold answer in diff</span></div>
          <div class="ln"><span class="t">gate</span><span class="tag d">[HELD-OUT]</span><span class="txt">0.62 → 0.71 · commit allowed</span></div>
          <div class="ln"><span class="t">merge</span><span class="tag te">[LEDGER]</span><span class="txt">version 7 · decision recorded</span></div>
          <div class="ln"><span class="t">report</span><span class="tag m">[RSI]</span><span class="txt">improving · 1 slot · cost 12 calls</span><span class="cursor"></span></div>
        </div>
        <div class="hud-side"><div class="metric"><div class="v">0.71</div><div class="k">HELD-OUT</div></div><div class="metric"><div class="v">1</div><div class="k">COMMITTED</div></div><div class="metric"><div class="v">12</div><div class="k">CALLS</div></div></div>
      </div>
    </section>

    <section class="proof-strip" aria-label="At a glance"><span>ONE ENGINE · MEASURED EVOLUTION</span><div><b>01</b> <span data-lang="zh">定义对象</span><span data-lang="en" hidden>Represent the artifact</span></div><div><b>02</b> <span data-lang="zh">并行探索</span><span data-lang="en" hidden>Explore in parallel</span></div><div><b>03</b> <span data-lang="zh">证据裁决</span><span data-lang="en" hidden>Gate on evidence</span></div></section>

    <section class="exp-section" id="how">
      <div class="section-label"><span data-lang="zh">工作原理</span><span data-lang="en" hidden>HOW IT WORKS</span><span>01 / 04</span></div>
      <div class="intro-grid">
        <h2><span data-lang="zh">定义。探索。<br><em>只合并更好的。</em></span><span data-lang="en" hidden>Define. Explore.<br><em>Merge only better.</em></span></h2>
        <div><p><span data-lang="zh">一个 <code>evolve()</code> 入口，战略决定改什么，Worker 并行提出候选，聚合器用 held-out 证据决定是否合并。策略槽位可以替换，循环保持不变。</span><span data-lang="en" hidden>One <code>evolve()</code> entry point. A strategy decides what changes, workers propose in parallel, and the aggregator merges only candidates that improve held-out evidence. Swap one policy slot; keep the loop.</span></p><a class="inline-link" href="evolution/"><span data-lang="zh">了解 evolve()</span><span data-lang="en" hidden>Meet evolve()</span> <span>↗</span></a></div>
      </div>
      <div class="process-line"><div><span>01</span><strong><span data-lang="zh">表示</span><span data-lang="en" hidden>Represent</span></strong><small><span data-lang="zh">用 Strategy 定义状态与可编辑内容</span><span data-lang="en" hidden>Use a Strategy to define state and editable content</span></small></div><div><span>02</span><strong><span data-lang="zh">探索</span><span data-lang="en" hidden>Explore</span></strong><small><span data-lang="zh">并行 rollout、提出 diff、解决冲突</span><span data-lang="en" hidden>Parallel rollouts, proposed diffs, conflict resolution</span></small></div><div><span>03</span><strong><span data-lang="zh">裁决</span><span data-lang="en" hidden>Gate</span></strong><small><span data-lang="zh">用 held-out 评估、守卫和人工审批决定</span><span data-lang="en" hidden>Held-out evaluation, guards and human approval</span></small></div></div>
    </section>

    <section class="exp-section feature-section" id="control-plane">
      <div class="section-label"><span data-lang="zh">开发预览 · 控制面</span><span data-lang="en" hidden>DEV PREVIEW · CONTROL PLANE</span><span>02 / 04</span></div>
      <div class="feature-heading"><h2><span data-lang="zh">从“能进化”<br><em>到“能放心跑”。</em></span><span data-lang="en" hidden>From “it evolves”<br><em>to “you can run it”.</em></span></h2><p><span data-lang="zh">这个预览包含仍在 review 的采纳、安全与可观测性工作：候选在评估前先过守卫，决策可记录，部署可灰度或停止，归档趋势可诊断。</span><span data-lang="en" hidden>The preview includes adoption, safety and observability work still under review upstream: guards run before evaluation, decisions are recorded, deployments can be canaried or stopped, and archive trends can be diagnosed.</span></p></div>
      <div class="capability-grid">
        <a href="leakage/"><span>01 / LEAKAGE</span><h3><span data-lang="zh">把答案挡在外面</span><span data-lang="en" hidden>Keep the answer key out</span></h3><p><span data-lang="zh">在候选购买 held-out 评估前，检查 diff 是否泄露 gold、task id 或私有语料。</span><span data-lang="en" hidden>Screen a candidate diff for gold answers, task ids or private corpus strings before it buys a held-out sweep.</span></p><small>LeakageGuard ↗</small></a>
        <a href="approval/"><span>02 / APPROVAL</span><h3><span data-lang="zh">高风险变更要人批</span><span data-lang="en" hidden>Require a human for risk</span></h3><p><span data-lang="zh">高风险自修改进入 JSONL 队列，审批绑定到真正被 review 的内容。</span><span data-lang="en" hidden>Queue high-risk self-modifications and bind approval to the exact content that was reviewed.</span></p><small>ApprovalGate ↗</small></a>
        <a href="runtime/"><span>03 / RUNTIME</span><h3><span data-lang="zh">一个受控会话</span><span data-lang="en" hidden>One guarded session</span></h3><p><span data-lang="zh">组合、注入验收、检查 kill switch、记录决策，一次调用完成。</span><span data-lang="en" hidden>Compose, inject acceptance, honour a pre-flight kill switch and record the decision in one call.</span></p><small>run_guarded ↗</small></a>
        <a href="safety-controller/"><span>04 / DEPLOYMENT</span><h3><span data-lang="zh">灰度、回滚、停止</span><span data-lang="en" hidden>Canary, roll back, stop</span></h3><p><span data-lang="zh">成对符号检验给出 promote / hold / rollback，文件开关停止下一次会话。</span><span data-lang="en" hidden>A paired sign test recommends promote/hold/rollback; a file switch stops the next session.</span></p><small>canary · KillSwitch ↗</small></a>
        <a href="diagnose/"><span>05 / DIAGNOSIS</span><h3><span data-lang="zh">说清为什么没学会</span><span data-lang="en" hidden>Name the failure mode</span></h3><p><span data-lang="zh">把最差 rollout、被拒候选和 outcome 直方图变成一个结论与下一步。</span><span data-lang="en" hidden>Turn the worst rollouts, refused candidates and outcome histogram into one verdict and the next step.</span></p><small>diagnose ↗</small></a>
        <a href="metrics/"><span>06 / OBSERVABILITY</span><h3><span data-lang="zh">盯住采纳率与成本</span><span data-lang="en" hidden>Watch acceptance and cost</span></h3><p><span data-lang="zh">把 decision records 聚合成采纳率、每次采纳成本与 Prometheus 导出。</span><span data-lang="en" hidden>Aggregate decision records into acceptance rate, cost per accepted change and a Prometheus export.</span></p><small>rsi_metrics ↗</small></a>
      </div>
      <div class="feature-tail"><span data-lang="zh">更多预览</span><span data-lang="en" hidden>MORE IN THIS PREVIEW</span><p><span data-lang="zh">决策日志、统计证据、边际收益停止、风险策略和算法锦标赛也都已进入导航。</span><span data-lang="en" hidden>Decision records, statistical evidence, marginal-gain stopping, risk policy and algorithm tournaments are also in the navigation.</span></p><a class="inline-link" href="decisions/"><span data-lang="zh">从决策日志开始</span><span data-lang="en" hidden>Start with the decision log</span> <span>↗</span></a></div>
    </section>

    <section class="exp-section" id="demo">
      <div class="section-label"><span data-lang="zh">运行方式</span><span data-lang="en" hidden>HOW A RUN LOOKS</span><span>03 / 04</span></div>
      <div class="demo-grid">
        <div><h2><span data-lang="zh">四个命令，<br><em>一次可复现的进化。</em></span><span data-lang="en" hidden>Four commands,<br><em>one reproducible evolution.</em></span></h2><p class="demo-copy"><span data-lang="zh">先 plan 看成本，再 start 后台运行；完成后 show 看差异，确认后 apply。每一步都能在 status 和决策记录里追溯。</span><span data-lang="en" hidden>Plan the cost, start the run in the background, inspect the diff with show, then apply after approval. Every step is traceable in status and the decision record.</span></p><p class="demo-copy"><span data-lang="zh">文档是英文的；这个预览页默认中文，可切换到 EN。</span><span data-lang="en" hidden>The docs are in English. This preview page defaults to Chinese; switch to EN at the top.</span></p><a class="inline-link" href="install/"><span data-lang="zh">打开快速开始</span><span data-lang="en" hidden>Open the quickstart</span> <span>↗</span></a></div>
        <div class="terminal-panel"><div class="terminal-head"><span class="dots"><i></i><i></i><i></i></span><span>agentdescent · terminal</span></div><pre><code>$ agentdescent plan spec.json
kind: skill_dir   tasks: 18   workers: 4   calls &lt;= 216

$ agentdescent start spec.json --detach
run_id: 7f3a1c   status: running

$ agentdescent status 7f3a1c
round 3/6   held-out 0.71   committed 1   rejected 2

$ agentdescent show 7f3a1c --json
outcomes: {committed: 1, below-threshold: 2}
decision: adopted · evidence: held-out gain</code></pre></div>
      </div>
    </section>

    <section class="exp-section" id="methods">
      <div class="section-label"><span data-lang="zh">方法不是限制</span><span data-lang="en" hidden>ALGORITHMS ARE EXAMPLES</span><span>04 / 04</span></div>
      <div class="methods-band"><div><h2><span data-lang="zh">同一个循环，<br><em>换不同的搜索。</em></span><span data-lang="en" hidden>One loop,<br><em>many search strategies.</em></span></h2><p><span data-lang="zh">ACE、GEPA、DGM、OpenEvolve 等 23 个方法端口都运行在同一个引擎上。它们展示如何替换 strategy、policy 或 aggregator，而不是限制你能做什么。</span><span data-lang="en" hidden>ACE, GEPA, DGM, OpenEvolve and 19 more method ports run on the same engine. They show how to replace a strategy, policy or aggregator — not what you are allowed to build.</span></p><a class="inline-link" href="self-evolution-examples/"><span data-lang="zh">查看全部 23 个方法</span><span data-lang="en" hidden>Explore all 23 methods</span> <span>↗</span></a></div><div class="method-list"><a href="algo-ace/"><b>ACE</b><span><span data-lang="zh">上下文 / playbook</span><span data-lang="en" hidden>Context / playbook</span></span><small>↗</small></a><a href="algo-gepa/"><b>GEPA</b><span><span data-lang="zh">Prompt / Pareto 搜索</span><span data-lang="en" hidden>Prompt / Pareto search</span></span><small>↗</small></a><a href="algo-dgm/"><b>DGM</b><span><span data-lang="zh">Agent harness / archive</span><span data-lang="en" hidden>Agent harness / archive</span></span><small>↗</small></a><a href="algo-openevolve/"><b>OpenEvolve</b><span><span data-lang="zh">程序 / islands</span><span data-lang="en" hidden>Program / islands</span></span><small>↗</small></a></div></div>
    </section>

    <section class="exp-cta"><div><span class="section-label"><span data-lang="zh">准备好就开始</span><span data-lang="en" hidden>READY WHEN YOU ARE</span></span><h2><span data-lang="zh">从一个 Agent 开始。</span><span data-lang="en" hidden>Start with your agent.</span></h2><p><span data-lang="zh">一条命令安装 AgentDescent，连接 PATH 上支持的 Agent。</span><span data-lang="en" hidden>One command installs AgentDescent and connects supported agents on your PATH.</span></p></div><a class="exp-button primary" href="install/"><span data-lang="zh">打开快速开始</span><span data-lang="en" hidden>Open quickstart</span> <span>↗</span></a></section>
  </main>

  <footer class="exp-footer"><a class="exp-brand" href="./"><span class="brand-mark">a<span>↘</span></span> agentdescent</a><span>Open source · MIT · HUGOXK preview</span><div><a href="https://github.com/Birfy/agentdescent">GitHub ↗</a><a href="docs/">Docs</a><a href="results/">Results</a></div></footer>
</div>
