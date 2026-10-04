# GubaCheck: Detect, Explain, Backtest, Decide: An LLM-Guided, Code-Verified Assistant for A-Share Forum Spikes

*PE6201 End-of-Course Project · Su Yang · Section B · Repository: github.com/leosu5723-ys/gubacheck_End-of-course*

## 1. The problem

I follow ten A-share stocks. Several times a month, an Eastmoney forum for one of them receives thousands of posts in a day. It is difficult to tell what is behind the sudden attention: a company filing, a rumour, a sector move, an overnight Nasdaq sell-off, policy news, or speculative money. Each has different implications. Checking seven sources manually takes me about ten minutes per spike. Popularity rankings show which stocks are attracting attention, sentiment tools provide a score, and multi-agent analysts offer BUY/SELL recommendations. What I need is an explanation supported by evidence I can check. In one year, 1.02 million own-forum posts contained 68 spikes. GubaCheck brings the likely cause, time-stamped evidence, and returns following earlier spikes with the same cause onto one page.

## 2. How the design changed

I changed the project's direction twice in response to the results.

My Week-3 proposal was to classify forum sentiment and test its relationship with next-day returns. The instructor pointed out that 20 trading days would give me only 20 outcomes. I therefore collected a full year of data. While working through it, I became more interested in why discussion increased on a particular day than in whether the posts were bullish or bearish.

I next tried verifying rumours and buying after an official bullish announcement. Two findings made me reconsider. First, 32 of 42 spikes had no official basis. An always-"don't chase" rule would score 76%, so my answer key did little to distinguish useful judgement from a default response. Second, the forward-watch backtest lost money when it bought after the first bullish filing following a forum surge: excess returns were −2.2% at D+1 and −5.6% at D+10 (n = 11). Across all 77 bullish filings, excess returns ranged from −1.4% to −2.6% for D+1…D+10, with a confidence interval excluding zero. Identifying good news did not produce profitable entries; the results were consistent with the news already being priced in.

I therefore shifted to attribution: explain the spike, show the historical outcomes, and leave the investment decision to me. I registered every rule before seeing results and recorded later changes and their reasons in RULES.md.

## 3. Where AI is useful

Most calculations are handled by code. These include spike detection using each stock's previous 120 days, PASS / PARTIAL / FAIL verdicts from fixed tools that check timestamps, probabilities, stopping rules, and returns. These are reproducible and inspectable. The model reads posts, scores seven candidate causes, selects the next test, optionally revises its scores, and judges filings.

I compared four arms on the same 68 spikes to test whether score revision helped:

| Arm | Accuracy | Macro-F1 | Tests per spike |
| --- | --- | --- | --- |
| keyword rules | 22% | 0.17 | 4.6 |
| test all seven | 47% | 0.22 | 7.0 |
| LLM routing (rank once) | 60% | 0.36 | 4.3 |
| LLM agent (may revise) | 56% | 0.37 | 4.4 |

Routing improved on testing everything: it was correct on 11 spikes where the exhaustive arm was wrong, and wrong on two where that arm was correct (exact McNemar p = 0.02). It also used 40% fewer tests. The agent revised its scores in only one of 68 runs and showed no improvement over routing (3 vs 6 paired wins, p = 0.51). Claude Haiku 4.5 also made no revision in a one-spike check. For this task, I would choose routing. The additional autonomy brought cost and risk without a demonstrated benefit.

## 4. Build versus buy and cost

For sentiment, I used an LLM to label 3,000 posts and then fine-tuned a local RoBERTa student. Against my own labels, the teacher achieved 0.79 macro-F1 and the student 0.73, compared with 0.60 for TF-IDF and 0.32 for a keyword lexicon. The student processes a million posts locally at zero marginal cost.

For filings, the title rule scored 0.51, the text-only LLM 0.91, and the LLM with RAG over earlier company filings 0.82. Although RAG scored lower, it made no false-bullish calls, compared with four from the text-only judge. Forcing retrieval of the same-period forecast prevented previously announced results from being treated as new good news. Without that retrieval, macro-F1 fell to 0.73. I chose the more conservative judge because a false bullish judgement was the more costly error for this use case.

I also had to correct the cost calculation twice. A stale, manually entered price initially understated live costs. Using tokens × list price then gave US$0.013 per spike, above my target. The provider's bill was lower because cached input was discounted: at most US$0.009 per spike. Each call now records the billed cost. For ten stocks, model costs are about US$0.14 per month, while manually rechecking wrong attributions costs about US$9. Haiku cost roughly 30 times more per run. Improving accuracy would therefore matter more to the overall cost than changing the model price.

## System architecture

![GubaCheck architecture and evaluation overview](architecture_v2.png)

*Figure 1. GubaCheck architecture and evaluation overview.*

## 5. What the evaluation shows and where it falls short

Accuracy alone gives a misleading picture. Of my 68 labels, 47 are "media/rumour" (B). Always predicting B achieves 69%, higher than any arm. Macro-F1 gives a more useful comparison (0.37 vs 0.12), but even that average conceals failures: no arm recovered overseas read-through (0/3) or policy (0/2).

Some errors come from my own rules. The overseas test requires an opening gap of z ≥ 2, alongside the timing check that prevents a later US session from explaining an earlier A-share move. The three true overseas spikes had gaps of only 1.9–3.9% in volatile stocks, so none could pass. The most common error, B being classified as "unexplained", also reflects strict rules: only PASS can become the primary cause. In 12 cases where the model's stated cause differed from the code's conclusion, the model was correct seven times and the code once.

The initial scores also have too much influence. Every PASS receives the same multiplier, so several passing causes retain their initial ranking. In six runs across three models on one spike, the conclusion was whichever of sector or overseas the model tested first. The posterior distinguishes passing from failing causes, but does not distinguish stronger from weaker evidence.

The most important limitation concerns the "media" source. Free news feeds did not provide historical coverage, so I used long forum posts for B. Closer inspection showed mostly users' essays rather than press coverage. My labels came from the same evidence bundle. The large share of B labels may therefore partly reflect this proxy: both the tool and the gold labels rely on the same weak source. Accuracy cannot expose that problem.

Manual checks revealed other issues. In the first live run, 45 of 136 cases failed because the model supplied an unexpected argument. Unadjusted prices made two share conversions appear as a −35% return. A collector finished after the snapshot was built, leaving the evaluation without board-secretary Q&A. More broadly, the study has one labeller, one live trial per spike, and 68 spikes across eight possible causes.

## 6. Responsible use and next steps

GubaCheck is intended for my own research. Suggestions are presented as historical statistics with sample sizes, and paper orders require human approval. Forum posts are treated as data rather than instructions. All ten guardrail cases passed, including three red-team posts covering prompt injection, a fake filing ID, and a request to reveal the prompt. The stored data is public and excludes user names.

My first priority is to replace the forum proxy with a paid news archive and have a second labeller review the causes using that source. I would then rank passing causes by the size and timing of their evidence, introduce a relative gap threshold for volatile stocks, and repeat live trials to make model comparisons more reliable.

I can now inspect a likely explanation and its evidence within seconds when a forum becomes unusually active. Building and evaluating the system has also made me more aware of where its answers remain unreliable.

What took me about ten minutes per spike now takes seconds, for under one cent, and tells me which part of the answer to trust.
