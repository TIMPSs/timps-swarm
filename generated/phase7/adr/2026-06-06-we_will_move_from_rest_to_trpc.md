# We will move from REST to tRPC

* Status: **proposed**  |  Date: 2026-06-06

## Context and Problem Statement

Our current REST API development and consumption process suffers from several inefficiencies, including a lack of end-to-end type safety, significant boilerplate for API clients, and challenges in maintaining consistent API contracts between frontend and backend teams. This leads to increased development time, runtime errors due to contract mismatches, and a suboptimal developer experience.

## Decision Drivers
* Improve Developer Productivity: Reduce the time and effort required to build and consume APIs.
* Enhance Type Safety: Eliminate runtime errors caused by mismatches between frontend expectations and backend API responses.
* Simplify API Maintenance: Streamline the process of evolving API contracts and ensuring consistency across the stack.
* Reduce Boilerplate: Minimize repetitive code for API client generation and data fetching.
* Optimize Performance (Developer Experience): Improve the ease of fetching exactly what's needed, reducing over/under-fetching.

## Considered Options
### Adopt tRPC
Incrementally migrate existing REST endpoints or build new features using tRPC, leveraging its end-to-end type safety and simplified API development for TypeScript applications.

**Good**
* Reduced Development Time: Compile-time type safety eliminates a class of runtime errors, speeding up debugging.
* Improved Developer Experience: Auto-completion and type inference for API calls directly from the backend schema.
* Lower Maintenance Cost: API contract changes are immediately reflected and validated across the stack, reducing manual effort.
* No Code Generation Step: Direct import of types from the backend, simplifying the build process and reducing complexity.
**Bad**
* TypeScript-Only: Requires a full TypeScript stack (frontend and backend), limiting interoperability with non-TS clients.
* Learning Curve: Team members unfamiliar with tRPC's specific patterns will require training, potentially causing an initial productivity dip.
* Ecosystem Lock-in: Tightly coupled to the tRPC ecosystem, potentially making it harder to switch frameworks later.
* Not for Public APIs: tRPC is designed for internal monorepo use; exposing it publicly requires an adapter or separate API layer.

### Enhance REST with OpenAPI/Swagger
Implement a robust OpenAPI (Swagger) specification for our existing REST APIs, generating client SDKs and enforcing schema validation at runtime.

**Good**
* Leverages Existing Knowledge: Builds upon current REST expertise within the team, minimizing a learning curve.
* Standardized Documentation: Provides excellent, machine-readable API documentation, improving discoverability.
* Public API Friendly: OpenAPI is a widely adopted standard, suitable for exposing public APIs.
* Client SDK Generation: Automates the creation of API clients in various languages, reducing manual boilerplate.
**Bad**
* Runtime Validation: Type safety is primarily enforced at runtime, not compile-time, still allowing for potential runtime errors.
* Manual Generation Step: Requires a separate step to generate client SDKs, adding complexity to the CI/CD pipeline.
* Over/Under-fetching: Does not inherently solve the problem of clients fetching too much or too little data, potentially impacting network latency.
* Increased Boilerplate: While client generation helps, the underlying data fetching logic can still be verbose compared to tRPC.

### Adopt GraphQL
Introduce GraphQL for new API development, providing a single, flexible endpoint that allows clients to precisely specify the data they need.

**Good**
* Reduced Network Latency: Clients can fetch all necessary data in a single request, minimizing round trips.
* Eliminates Over/Under-fetching: Clients request only the data they need, optimizing data transfer and bandwidth usage.
* Strong Typing & Introspection: GraphQL schema provides strong type guarantees and excellent discoverability for clients.
* Flexible Client Development: Empowers frontend teams to evolve data requirements without requiring backend changes.
**Bad**
* Steeper Learning Curve: Requires significant investment in learning GraphQL concepts (schemas, resolvers, queries, mutations) for the entire team.
* Increased Backend Complexity: Requires a new server layer with resolver logic, potentially increasing backend development time and maintenance cost.
* Caching Challenges: Caching strategies can be more complex than with traditional REST, potentially impacting performance.
* Potential for N+1 Problems: Inefficient resolver implementations can lead to performance bottlenecks if not carefully optimized.

## Decision Outcome
Chosen option: **Adopt tRPC**

### Positive consequences
* Reduced API-related Runtime Errors: We expect a 70% reduction in production bugs related to API contract mismatches within 3 months of migrating critical paths.
* Increased Developer Velocity: Frontend and backend teams will experience a 20% increase in feature delivery speed for API-dependent features due to improved DX and reduced debugging time, measurable within 6 months.
* Simplified API Evolution: Changes to API contracts will be propagated and validated across the stack with minimal manual effort, reducing the risk of breaking changes and associated maintenance costs.
* Improved Onboarding for New Developers: New team members will be able to understand and interact with the API more quickly due to strong typing and auto-completion, reducing onboarding time by an estimated 25%.
### Negative consequences
* Initial Productivity Dip: The team will experience a 10-20% dip in productivity during the initial learning and migration phase (first 1-2 months) due to the new technology adoption.
* Limited Public API Exposure: We will need to maintain a separate REST or GraphQL layer if we decide to expose parts of our API publicly to non-TypeScript clients, incurring additional development and maintenance overhead.
* Increased Build Times (Monorepo): If the frontend and backend are in a monorepo, changes to backend types might trigger more frequent frontend rebuilds, potentially increasing CI/CD times slightly (e.g., 5-10% for affected pipelines).
### Follow-up actions
- [ ] Conduct tRPC Training: Organize a workshop for all relevant frontend and backend engineers on tRPC best practices and patterns within 2 weeks.
- [ ] Pilot Project Implementation: Select a small, non-critical new feature or existing endpoint to migrate to tRPC as a pilot project within 1 month to gain practical experience.
- [ ] Establish Migration Strategy: Define a clear strategy for incremental migration of existing REST endpoints to tRPC, including deprecation plans and timeline, within 2 months.
- [ ] Update CI/CD Pipelines: Integrate tRPC-specific build and test steps into our CI/CD pipelines as needed to ensure continuous integration and deployment.
- [ ] Monitor Key Metrics: Track API-related bug reports, developer satisfaction surveys, and feature delivery times to quantitatively measure the impact of the change over the next 6-12 months.
