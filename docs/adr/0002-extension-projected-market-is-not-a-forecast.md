# Extension "projected market" carries value forward, it is not a forward forecast

The extension decision needs a dollar figure for what a player would command in the season he
would otherwise reach free agency. We define **projected market** as the player's *current*
percent-of-cap model value, carried forward to that season at the CBA cap escalator and expressed
in that season's dollars. Player trajectory enters only through the model's current-season lag
features (a rising young player already values higher today); we do **not** simulate future
production, aging curves, or role change.

This is deliberate. A true multi-year production forecast is a separate, much larger modeling
effort with its own backtest and uncertainty story, and shipping a naive one behind an
authoritative-looking dollar figure would overclaim — the same failure mode ADR-0001 guards
against on the valuation side. Percent-of-cap is already cap-normalized, so carrying it forward is
honest and cheap, and the UI labels it plainly (a caveat states it is not a forward projection; a
trajectory note flags rising/declining current-season signal). If a backtested aging forecast
lands later, it can replace the carry-forward here without changing the surface's contract.

The rejected alternative — a bare extrapolated stat line feeding a dollar projection — was declined
because it reads as precision the model does not have.
