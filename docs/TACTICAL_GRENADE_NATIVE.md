# Grenade native execution evidence

September 7, 2026. Static analysis of the local reference executable, using
`diagnostics/tactical_map.py decompile` with Ghidra `-readOnly -noanalysis`.
These findings narrow the next native trial; they do not enable throws.

## Verified static chain

| Native address | Observed code behavior | Practical consequence |
| --- | --- | --- |
| `0xaa45b0`, `0xaa4620`, `0xaa4690` | Construct fragmentation, AT and smoke actions with names `throw_ap_grenade`, `throw_at_grenade`, `throw_sk_grenade`. | Keep the existing action identity and inventory checks. |
| Action virtual offset `0x68`, `0xaa41c0` | Chooses a nearby actor from an action-filtered list, with a preference determined by virtual offset `0x5c`. | This selects an actor; it is not a ballistic-clearance predicate. |
| `0xaa58a0` | Uses the selected actor, constructs an order through `0x8d9ab0`, then submits it through `0x8317c0`. | Do not call this as a read-only preflight. |
| `0x8d9ab0`, vtable `0xdf9e68`, name method `0x8dd2c0` | Allocates an order named `eWeaponShot`, copies the filter and target, and clears byte `+0x81`. | An accepted grenade command starts a weapon-order lifecycle; it does not establish emission. |
| `0x8db5a0` | Retries equipment selection through `0x8d9960` before advancing to `0x8dada0`. | Observe selected equipment and inventory consumption separately. |
| `0x8dada0` | Checks planar target distance against a derived weapon range. The out-of-range branch creates a movement suborder; later branches call `0x851d60` and may enter additional recovery. | A nominal throw can cause movement. A live trial must bound displacement and distinguish approach from throwing. |
| `0x8daab0` | Tracks repeated failure/time at a position and may create further movement or targeting suborders. | Do not equate a persistent outstanding order with useful progress. |
| `0x851d60` | Machine code reads an object through `ECX+8`, builds a stack context, calls `0x852ab0`, preserves EAX and returns with `ret 0x14`. | Five stack arguments and the object context are required; the decompiler's four-argument `void` signature is incorrect. This is not a callable query ABI. |
| `0x852ab0` | Writes output/global state, calls a shooter virtual method, and can dispatch through `0x8531f0`. | The fire wrapper is stateful; do not invoke it to test feasibility. Emission/effect attribution still needs live correlation. |

The apparent range comes from `0x843360` or `0x843830` depending on weapon
behavior. Neither function alone establishes a clear trajectory, safe blast
radius, fuse timing, target suitability or a completed throw. The numeric order
states remain raw until correlated with live observations. In particular, state
6 must not be labelled “grenade thrown” from this analysis.

## Saved analysis

Files under `validation/tactical_mapping_20260907/`:

- `cqc_target_selection_20260907.txt`: selection, order construction and admission.
- `cqc_order_lifecycle_20260907.txt`: order identity and serialization methods.
- `cqc_weapon_execution_20260907.txt`: lifecycle update and child-order creation.
- `cqc_shot_states_20260907.txt`: initial state and equipment-selection retry.
- `cqc_shot_feasibility_20260907.txt`: range, attempt and recovery branches.
- `cqc_fire_boundary_20260907.txt`: fire wrapper and repositioning branches.
- `cqc_fire_dispatch_20260907.txt`: stateful fire dispatch.
- `cqc_execution_manifest_20260907.json`: reference-executable and analysis hashes,
  plus the fire wrapper's complete instruction sequence.

Each analysis has its matching Ghidra log. No game mutation was performed for
these decompilations. Existing live inventory evidence remains valid only for
inventory availability.

## Next verification

Next correlate the downstream `0x8531f0` path with observed projectile creation.
A native trial needs a reconciled controlled match,
one known grenade carrier, a bounded safe target, observed equipment selection,
projectile creation, inventory change and effect. Protecting the throw animation
and checking friendly clearance must be verified before enabling tactical throws.
Smoke additionally needs an actual crossing or withdrawal plan and observation
of the smoke effect; a submitted command alone is insufficient.

The previous match's hidden statistics were subsequently recovered from the
durable completion/exit/statistics sequence through guarded `save-ai-results`;
see the [army operations evidence](TACTICAL_ARMY_OPERATIONS.md). The current
obstacle to a fresh controlled trial is two remote human players in the lobby.
The AI-only guard rejected test setup, and the session was left untouched.
