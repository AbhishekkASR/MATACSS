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
deterministic development provider uses only public prompt wording. Configured
OpenAI/Azure implementations may propose additional bounded cases, but no
provider can execute code, access Docker or the database, or see hidden cases.

Generated cases are persisted only as advisory feedback. They are not inserted
into `QuestionTestCase`, used by scoring, or treated as official evaluation
inputs. Explicit verification and promotion of generated cases into the
official evaluation set are not implemented.
