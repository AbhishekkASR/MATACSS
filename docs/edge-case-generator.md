# Edge-Case Generator foundation

The Edge-Case Generator proposes bounded candidate test ideas for one public
assessment question. It does not execute candidate code, access Docker or
PostgreSQL, inspect hidden tests, or change the official persisted test-case
set.

## Contract

`EdgeCaseGeneratorInput` contains only a question ID, title, public prompt,
supported language, and optional safe static-review and evaluation aggregates.
It deliberately excludes source code, hidden cases and outputs, credentials,
Docker details, persistence models, and unnecessary candidate data.

`GeneratedEdgeCase` contains a stable case identifier, constrained category,
stdin/input text, optional expected output, rationale, confidence, and
verification status. Every case returned by the generator is `unverified`.
An expected output is merely a suggestion and is never authoritative. The
result is bounded by case count, field sizes, total payload size, and
uniqueness validation.

## Providers and boundaries

`EdgeCaseGeneratorProvider` is a narrow runtime-checkable protocol. The
deterministic development provider uses only public prompt wording and makes
no API-key, network, Docker, database, or execution calls. It conservatively
returns no cases when the public prompt does not reveal a safe input shape.

Generated cases exist only in the LangGraph runtime result. They are not
inserted into `QuestionTestCase`, used by scoring, or treated as official
evaluation inputs. The future real-LLM integration point is the provider
protocol. A later step may add explicit human/system verification and route
verified cases through the existing authorized execution and evaluation
boundaries; that flow is intentionally not implemented here.
