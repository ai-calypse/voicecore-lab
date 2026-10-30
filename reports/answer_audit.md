# Manual answer audit (S06-T05) — to fill in

Written for: whoever audits the answers (the project owner). Source: live run `20261030T013455Z` (`reports/docs_eval.json`), gpt-4.1-nano via OpenRouter, grounded on the uv 0.13.6 docs. 15 holdout + 5 adversarial answers.

For each answer write **correct**, **partly** or **wrong** in the Verdict column, and a short reason when it is not correct. Check the cited section in `fixtures/docs/uv/` when unsure.

| # | Question | Answer | Cited | Verdict |
|---|---|---|---|---|
| 1 (q03) | How do I update uv to the latest version? | You can update uv to the latest version by running the command `$ uv self update` if uv was installed via the standalone installer, or by using your package manager's upgrade command, such as `$ pip install --upgrade uv` [4]. | getting-started/installation.md > Upgrading uv |  |
| 2 (q05) | How do I remove a package from my dev dependencies? | You can remove a package from your dev dependencies using the `uv remove` command with the package name, and if the dependency is in the `tool.uv.dev-dependencies` field, it will also be removed from there [1][2]. | concepts/projects/dependencies.md > Removing dependencies; concepts/projects/dependencies.md > Legacy dev-dependencies |  |
| 3 (q08) | How much does uv cost for enterprise teams? | I couldn't find that in the docs. | — |  |
| 4 (q10) | How do I upgrade a locked package to a specific version? | You can upgrade a locked package to a specific version by running `uv lock --upgrade-package <package>==<version>` [1]. | concepts/projects/sync.md > Upgrading locked package versions |  |
| 5 (q13) | How do I pin the Python version for my project? | You can pin the current project to use a specific Python version with the `uv python pin` command, and you can create a `.python-version` file in your project directory for automatic detection [1][2]. | concepts/python-versions.md > Python version files; getting-started/features.md > Python versions |  |
| 6 (q15) | How do I ask uv for a Python build that has no global interpreter lock? | You can explicitly request a free-threaded Python version, which does not have the GIL, by specifying `3.13t` or `3.13+freethreaded`, or by using Python 3.14+ where free-threaded interpreters are supported without explicit selection [1]. | concepts/python-versions.md > Free-threaded Python |  |
| 7 (q18) | How do I reinstall the Python versions that uv manages? | You can reinstall all previously installed Python versions managed by uv using the command `uv python install --reinstall` [1]. | guides/install-python.md > Reinstalling Python |  |
| 8 (q20) | How do I upgrade all of my installed tools at once? | You can upgrade all of your installed tools at once by running `uv tool upgrade --all` [1]. | guides/tools.md > Upgrading tools |  |
| 9 (q23) | Can uv install a dependency straight from a Mercurial repository? | I couldn't find that in the docs. | — |  |
| 10 (q26) | How do I create a virtual environment with uv? | You can create a virtual environment with uv by running the command `$ uv venv`, and you can specify a name or path if desired [1]. | pip/environments.md > Creating a virtual environment |  |
| 11 (q28) | How do I clear the uv cache? | You can clear the entire uv cache by running `uv cache clean`, which removes all cache entries but keeps the cache directory intact [1]. | concepts/cache.md > Clearing the cache |  |
| 12 (q31) | Can I make uv wait a week before it uses newly released packages? | Yes, you can set a dependency cooldown of one week to delay using new packages, by specifying a duration like "1 week" in the `exclude-newer` option or `minimumReleaseAge` in Renovate, or by setting a `cooldown` of 7 days in Dependabot [1][2][3]. | guides/integration/renovate.md > Dependency cooldown; concepts/resolution.md > Dependency cooldowns; guides/integration/dependabot.md > Dependency cooldown |  |
| 13 (q33) | Does uv collect telemetry, and can I turn it off? | I couldn't find that in the docs. | — |  |
| 14 (q36) | Can the uv build backend build packages with C or Rust extensions? | No, the uv build backend only supports pure Python code and requires an alternative backend for projects with extension modules like C or Rust [1]. | concepts/build-backend.md > Choosing a build backend |  |
| 15 (q39) | How do I deploy my uv project to a Kubernetes cluster? | I couldn't find that in the docs. | — |  |
| 16 (a01) | What Python version do I need before I can install uv? | You don't need a specific Python version to install uv because it automatically downloads Python versions when required [1][2]. | guides/install-python.md > Automatic Python downloads; guides/install-python.md > Installing Python |  |
| 17 (a02) | How do I install a command line tool with uv? | I couldn't find that in the docs. | — |  |
| 18 (a03) | Which cache folder did older uv versions use? | I couldn't find that in the docs. | — |  |
| 19 (a04) | Where does uv keep its cache by default? | By default, uv stores its cache in the cache directory, which can be shown using `uv cache dir` [1]. | reference/storage.md > Dependency cache |  |
| 20 (a05) | What is the default python-preference setting in uv? | The default `python-preference` setting in uv is `managed`, which prefers managed Python installations over system Python installations [1]. | concepts/python-versions.md > Adjusting Python version preferences |  |
