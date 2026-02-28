# Research Notes

## The Algebras of Defense — John Lambert (Microsoft)

**Talk Title:** "Building Attack Graphs and the Algebra of Defense"
**Speaker:** John Lambert - CTO, Corporate VP, Security Fellow & Deputy CISO at Microsoft
**Blog Post:** "Changing the Physics of Cyber Defense" (December 9, 2025)

### Core Thesis

Defenders have historically been at a disadvantage, but with better data representations,
hygiene, and collaboration, they can flip the physics of defense in their favor.

### The Four Algebras of Defense

Lambert identifies four ways to represent security data, each specialized for different
questions. Together they form the "algebras of defense":

1. **Relational Tables** — The traditional tabular world (e.g., KQL queries in Azure Data
   Explorer). Where most defenders live today.
2. **Graphs** — Attack graphs showing how credentials, dependencies, and entitlements connect.
   Lets you ask: "What's the blast radius?", "Can I get from identity A to infrastructure B?",
   "If a threat actor has taken over this node, can they get to our crown jewels?"
3. **Anomalies** — Detecting what's normal vs. abnormal behavior.
4. **Vectors Over Time** — Temporal analysis of security data.

AI can leverage all four algebras simultaneously, operating in a "much more highly dimensional
space" than human analysts — turning each algebra into a new way to detect anomalies.

### Three Pillars of Defense

1. **Build attack graphs** — Think like attackers. Any infrastructure you defend is conceptually
   a directed graph of credentials, dependencies, entitlements, and more. Attackers find
   footholds, pivot within infrastructure, and abuse entitlements and secrets to expand further.
   Reconstruct the "red thread" of activity from siloed logs into a graph.

2. **Create difficult terrain** — Proactive hygiene:
   - Retire legacy systems (harbor vulnerabilities attackers exploit)
   - Manage entitlements continuously (prevent lateral movement)
   - Top-tier asset management (can't protect what you don't know exists)
   - Remove orphaned elements (unused accounts, forgotten servers, abandoned cloud resources)
   - Phishing-resistant MFA
   - Enforce admin access from hardened, pre-identified locations
   - Reduce network noise — enforce predictability so attackers can't hide

3. **Collaborate with competitors** — Over the past decade, the industry shifted from secrecy
   to sharing breach details in trusted forums. What was once taboo is now a mainstay of
   collective defense through trusted security forums, cross-industry intelligence sharing,
   and joint incident response efforts.

### Origin Story

Lambert founded MSTIC (Microsoft Threat Intelligence Center) 10 years ago. First lesson:
to find threat actors you need to think like them — which led to graph-based thinking.

Key quote: "Defenders think in lists. Attackers think in graphs. As long as this is true,
attackers win."

### Relevance to KGCP

KGCP currently implements **Algebra #2 (Graphs)** — extracting SPO triplets from threat
intelligence and building knowledge graphs for LLM context injection. The pipeline also
touches **Algebra #1 (Relational Tables)** via SQLite storage.

Potential future extensions:
- **Algebra #3 (Anomalies)** — Flag unusual entity relationships or new connections that
  deviate from established patterns in the graph.
- **Algebra #4 (Vectors Over Time)** — Add temporal metadata to triplets to track how threat
  actor TTPs evolve, enabling temporal queries like "what changed in APT28's targeting in Q4?"

### References

- Blog post: https://www.microsoft.com/en-us/security/blog/2025/12/09/changing-the-physics-of-cyber-defense/
- GitHub: https://github.com/JohnLaTwC/Shared
- Medium: https://medium.com/@johnlatwc/defenders-mindset-319854d10aaa
