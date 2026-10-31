# KServe AI Platform Usage Dashboard — Panel Guide

**Audience:** Executive and business stakeholders  
**Purpose:** This dashboard gives the infrastructure team and leadership a real-time view of how effectively the organization is using its AI model serving platform — which teams are consuming capacity, whether the hardware is being used efficiently, and how well the models are performing for end users.

---

## How to Read This Dashboard

At the top of the dashboard are **filter controls** (called variables). These let you narrow the view to a specific cluster, team, model, or application. All panels update instantly when you change a filter. By default, everything is shown.

| Filter | What it does |
|---|---|
| **Cluster** | Limits the view to one or more of your Kubernetes clusters |
| **Namespace** | Narrows to a specific environment or team workspace within a cluster |
| **Model** | Shows data for only the selected AI models (e.g. gemma-4-31b, meta-llama-3-1-8b-instruct) |
| **Line of Business** | Filters by the LOB tag attached to each request — useful for chargeback and attribution |
| **App ID** | Narrows to requests from a specific application or integration |
| **Use Case** | Filters by the declared workload type (e.g. summarization, translation, guardrails) |

---

## Section 1 — At-a-Glance Overview

These eight tiles at the top of the dashboard give you an instant health check without reading any charts.

---

### Total Requests
**What it shows:** The total number of AI inference requests completed during the selected time window.

**Why it matters:** This is the primary demand signal for the platform. A rising number indicates growing adoption across the organization. Use it to track month-over-month growth and correlate spikes with specific launches or campaigns.

---

### Total Tokens Processed
**What it shows:** The cumulative count of "tokens" — the units of text the AI models read and produce — across all requests in the time window. This includes both what users sent to the model (input) and what the model generated in response (output).

**Why it matters:** Token volume is the most accurate proxy for compute cost and GPU utilization. Two applications may submit the same number of requests but one might process ten times as many tokens if it uses longer documents or longer responses. Use this figure for infrastructure cost allocation and chargeback conversations with business units.

---

### Current Request Rate
**What it shows:** How many AI inference requests are arriving per second right now.

**Why it matters:** This is the live load indicator. A sudden spike may signal a new integration going live, a traffic event, or a misconfigured client sending runaway requests. A drop may indicate an outage or a team pausing their workload.

---

### Active Models
**What it shows:** The number of distinct AI models currently receiving traffic on the platform.

**Why it matters:** A higher number means the platform is serving a diverse portfolio of use cases. Tracking this over time shows whether teams are adopting new models or consolidating onto fewer ones.

---

### P99 Time to First Token
**What it shows:** The 99th-percentile "Time to First Token" (TTFT) in milliseconds — meaning 99% of requests begin receiving a response within this time. The color changes from green to yellow to red as values rise.

**Why it matters:** TTFT is what users experience as "how long did I wait before anything happened." A high TTFT means users stare at a loading state for too long. Green means the platform is responsive; red means there is a queue or capacity problem that degrades user experience.

---

### P99 Time Per Output Token
**What it shows:** The 99th-percentile inter-token latency in milliseconds — how quickly the model produces each successive word after the first one arrives.

**Why it matters:** This governs streaming responsiveness. A slow value here means text appears to trickle out word by word, which feels sluggish even if the first response was fast. Larger models inherently have higher values, but sustained increases under load indicate the hardware is being shared across too many concurrent users.

---

### GPU KV Cache Utilization
**What it shows:** The percentage of GPU memory allocated to hold "context" (the working memory models use while processing requests) that is currently in use. The color threshold turns yellow at 70% and red at 90%.

**Why it matters:** When GPU cache approaches 100%, the system starts evicting in-progress requests from memory, forcing them to restart — this hurts both performance and efficiency. Sustained high utilization is a strong signal to add capacity or adjust model deployment configuration.

---

### Queued Requests
**What it shows:** The number of requests currently waiting to be processed because all GPU slots are occupied.

**Why it matters:** A non-zero queue is normal during peak load. A consistently large or growing queue means the platform cannot keep up with demand and users are experiencing delays. This is the most direct indicator that additional hardware or model replicas are needed.

---

## Section 2 — Request Traffic

These panels show where demand is coming from and how it is distributed.

---

### Request Rate by Cluster
**What it shows:** A time-series chart of requests per second, with a separate line for each cluster.

**Why it matters:** This shows whether load is balanced across your infrastructure or whether one cluster is carrying a disproportionate share. Large differences between clusters can indicate that load balancing is not working correctly or that teams are routing all traffic to a single environment.

---

### Request Rate by Model
**What it shows:** Requests per second broken out by individual AI model.

**Why it matters:** This reveals which models are the most popular across the organization. It helps prioritize where to focus capacity investments and identify models that are receiving unexpectedly high or low adoption after a deployment.

---

## Section 3 — Token Economics

These panels quantify the actual compute being consumed, which is a more accurate cost signal than request counts.

---

### Token Throughput — Prompt vs. Generation
**What it shows:** Two lines over time — the rate of tokens the platform is reading from users (prompt/input tokens) versus the rate of tokens it is generating in response (generation/output tokens). A dashed third line shows the combined total.

**Why it matters:** The ratio of input to output reveals how the platform is being used. Applications that send large documents for summarization will show high input and low output. Chatbots and code generation tools will show more balanced or output-heavy patterns. This informs capacity planning because input and output processing have different GPU costs.

---

### Token Throughput by Model
**What it shows:** Combined token rate (input + output) per model over time.

**Why it matters:** Even if a model handles few requests, it might consume a disproportionate amount of compute if each request involves very long text. This chart identifies the highest-cost models in terms of raw GPU work, regardless of request volume.

---

## Section 4 — Latency & Performance

These panels track how quickly the platform responds to users, broken into the components that make up total response time.

---

### Time to First Token (TTFT) — Percentiles
**What it shows:** Three lines — P50 (median), P90, and P99 — for the time between a request arriving and the first word of the response appearing.

**Why it matters:** The gap between P50 and P99 reveals consistency. A narrow gap means most users have a similar experience. A wide gap means some users are waiting much longer than others — often because they joined a queue behind a large batch. Rising P99 is usually the first sign of capacity pressure.

---

### Time Per Output Token (TPOT) — Percentiles
**What it shows:** P50, P90, and P99 for the time between successive output tokens during generation.

**Why it matters:** This governs the streaming typing speed users see. It typically rises when many users are sharing the same model simultaneously, because the GPU is dividing its throughput across all of them. A rising trend here means the model is oversubscribed and individual response quality is degrading.

---

### Request Queue Time — Percentiles
**What it shows:** P50, P90, and P99 for how long requests waited in the queue before any GPU work began.

**Why it matters:** Queue time is pure waiting with no value delivered to the user. Even a fast model feels slow if requests queue for several seconds. This panel directly measures whether the platform has enough capacity to serve demand without making users wait.

---

### TTFT by Model (P99)
**What it shows:** The P99 Time to First Token plotted separately for each model.

**Why it matters:** Different models have inherently different latency profiles based on their size and architecture. This chart lets you compare models on a level playing field and identify if any specific model is significantly underperforming relative to its peers — which may indicate a configuration issue or a need for more dedicated replicas.

---

### TPOT by Model (P99)
**What it shows:** The P99 Time Per Output Token for each model, plotted separately.

**Why it matters:** Larger models generate tokens more slowly by nature. This chart provides a benchmark for each model and makes it easy to spot when a model's throughput degrades unexpectedly — for example, when a new high-traffic application is sharing capacity with an existing one.

---

## Section 5 — Queue & Concurrency

These panels show the real-time workload the platform is handling across its processing pipeline.

---

### Active Requests — Running vs. Waiting
**What it shows:** Three series per cluster — how many requests are actively being processed (running), how many are waiting for a GPU slot (waiting), and how many have been temporarily offloaded from GPU memory to slower CPU memory (swapped).

**Why it matters:** This is the live utilization heartbeat. A healthy platform has mostly "running" requests and a small, stable "waiting" count. A growing "waiting" line means the platform is at capacity. Any "swapped" requests indicate GPU memory pressure — the system is managing an overload by temporarily storing work elsewhere at a performance cost.

---

### Concurrent Requests by Model
**What it shows:** How many requests each model is actively processing at any given moment, stacked so the total height represents the cluster's overall concurrency.

**Why it matters:** This shows which models are occupying the most simultaneous GPU slots. It is useful for capacity planning and for understanding whether a model's poor latency is caused by high concurrency (many users sharing one instance) rather than the model itself.

---

## Section 6 — Cache & Hardware Efficiency

These panels measure how well the platform is using its GPU hardware — the most expensive part of the infrastructure.

---

### GPU KV Cache Utilization by Model
**What it shows:** The percentage of GPU working memory (KV cache) used by each model over time, with color thresholds at 70% (yellow) and 90% (red).

**Why it matters:** GPU memory is the primary resource constraint for AI model serving. When cache utilization is low, the hardware is underutilized and there is room to serve more users. When it approaches 100%, the system starts degrading — new requests cannot be efficiently batched and some may be evicted and delayed. Sustained high utilization across all models is a clear signal to expand GPU capacity.

---

### Prefix Cache Hit Rate
**What it shows:** The percentage of request prefixes (the beginning of prompts) that were already cached from a previous request, broken down by model.

**Why it matters:** Many AI applications send similar prompt beginnings — system instructions, document context, or chat history — on every request. When these are cached, the GPU skips reprocessing them, which dramatically reduces Time to First Token and saves compute. A high hit rate (above 50%) means the platform is working efficiently for repetitive workloads. A low hit rate on a high-traffic model may indicate an opportunity to restructure prompts to enable more caching.

---

### CPU KV Cache Utilization by Model
**What it shows:** The percentage of CPU memory being used as overflow storage for model context, colored red at even modest values.

**Why it matters:** Ideally this should be near zero. CPU cache is a fallback when GPU memory is exhausted — it is significantly slower and degrades response times. Any sustained CPU cache utilization is a warning sign of GPU memory pressure and should be investigated promptly.

---

## Section 7 — Business Attribution

These panels answer the question: *who is using the AI platform, and for what?*

---

### Request Share by Line of Business
**What it shows:** A pie chart of inference requests distributed across each Line of Business tag.

**Why it matters:** This is the primary view for chargeback and showback conversations. It shows which business units are driving the most platform usage and helps leadership allocate infrastructure costs proportionally. It also reveals if usage is concentrated in one area — indicating either strong adoption or a dependency risk.

---

### Token Consumption by Line of Business
**What it shows:** A donut chart of total token volume (input + output) per Line of Business.

**Why it matters:** Because token volume is a more accurate cost proxy than request count, this view complements the request pie chart. A business unit that submits fewer requests but uses much more of the token budget — because its application works with large documents — will stand out here. Use both charts together for fair cost attribution.

---

### Requests by Use Case
**What it shows:** A horizontal bar chart ranking the declared use cases (e.g. summarization, translation, guardrails, code generation) by request volume.

**Why it matters:** This shows what the platform is actually being used for at a business level. It validates whether investments in specific model types are being consumed as intended and surfaces emerging use cases that may require dedicated capacity or new model deployments.

---

## Section 8 — Top Consumers & Model Summary

These tables provide the detailed breakdowns useful for planning conversations and business reviews.

---

### App ID Usage Summary
**What it shows:** A table listing every application that has sent requests during the selected time window. Each row shows the application's LOB tag, its total request count, total tokens consumed, and current request rate. The table is sorted by token consumption (highest first) and includes column totals at the bottom.

**Why it matters:** This is the chargeback ledger. It identifies the top-consuming applications by cost-equivalent compute. Use it to have informed conversations with application teams about their usage patterns, enforce quotas, and plan capacity for high-growth integrations. The color gradients make the highest consumers immediately visible without reading numbers.

---

### Model Performance Summary
**What it shows:** A table with one row per model showing: current request rate, total requests in the window, P99 Time to First Token, P99 Time Per Output Token, token throughput, and GPU cache utilization displayed as a colored progress bar.

**Why it matters:** This is the infrastructure team's per-model health scorecard. It surfaces models that are heavily loaded (high requests, full cache), models that are slow relative to their peers (high TTFT/TPOT), and models that are underutilized (low req/s, low cache). Use it to decide where to add replicas, where to consolidate, and which models to highlight in an executive review.

---

## Section 9 — Request Outcomes & Errors

These panels show the quality and completeness of the responses the platform is producing.

---

### Request Outcomes by Finished Reason
**What it shows:** A stacked chart showing how requests completed over time, broken into four categories: **stop** (completed normally), **length** (cut off because it hit the maximum response size), **abort** (cancelled by the calling application before finishing), and **error** (failed due to a server-side problem).

**Why it matters:** In a healthy platform, nearly all requests should finish with "stop." A rising "length" share means applications are setting their response limits too low, causing users to receive incomplete answers. A rising "abort" share may indicate client-side timeouts — users giving up before the response arrives. A rising "error" share requires immediate investigation. This chart provides the first indication of degrading response quality that would not be visible from request volume alone.

---

### Requests Truncated at max_tokens
**What it shows:** The rate of requests cut off by the response length limit, broken out by model.

**Why it matters:** Truncated responses are incomplete answers delivered to users. If a specific model shows a persistently high truncation rate, the application teams consuming that model may need to raise their response length settings, or the use case may be better served by a model that generates more concise answers.

---

### Preemptions Over Time
**What it shows:** The rate at which requests are being evicted from GPU memory mid-processing and forced to restart, broken out by model.

**Why it matters:** Preemptions are a sign of GPU memory overload. When too many long requests are in flight simultaneously, the system cannot hold all of their working state in GPU memory and must pause some requests, save their state to CPU memory, and restart them later. Each preemption wastes GPU cycles and increases latency for the affected user. A non-zero and rising preemption rate is a strong capacity alert.
