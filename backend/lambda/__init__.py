"""Lambda entrypoints: thin handlers over `backend/tools/`.

`architecture.md` -> Invariants #3: the background job must call the same
`backend/tools/` functions the live agent uses for any mutation, never
duplicate the rule. Everything here is a handler shape (parse the event,
call into `tools`, shape the response) and nothing more -- the decision
logic itself lives in `tools`, not here, so a Lambda and a future caller
of the same tool function can never drift apart.

Modules:
    background_scan: the EventBridge-triggered daily scan -- one
        invocation, one clinic, over `tools.automation.run_daily_scan`.
"""
