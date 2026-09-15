# Recipes And Answer Contract

## Worked example

> *"My chart snaps to the right edge every time new data arrives."*

1. **Layers involved:** data model (4) and time scale (3).
2. **Suspect:** the code calls `series.setData(...)` on every tick instead of `series.update(...)`. `setData` resets the visible range.
3. **Verify:** ask whether the call path is `setData` or `update`. If `setData`, ask whether the visible logical range is captured before and restored after — the v4-era workaround.
4. **Fix:** switch to `series.update(bar)` for incremental ticks; reserve `setData` for full-history replacement; only use `chart.timeScale().scrollToRealTime()` if the user explicitly wants follow-the-latest behavior.
5. **References:** `website/tutorials/demos/realtime-updates.js`, `website/docs/time-scale.md`.

## Code-generation rules

- **Default to v5.** Assume v5 APIs unless the user's installed package or prompt pins an older version. If they're on v4, explain the v5 migration point instead of mixing syntaxes.
- **Use real option names.** In consumer apps, grep `node_modules/lightweight-charts/dist/typings.d.ts`; in the upstream repo, grep `dist/typings.d.ts` or `src/api/options/`. Many similarly-named options exist across chart/series/scale — confirm which level owns the option.
- **Minimal snippets.** One feature per code block. Combining markers + watermark + custom pane primitive in one snippet hides which API does what.
- **Match the user's framework.** A React user wants the `useEffect` lifecycle; a vanilla user does not.
- **Don't invent.** If an API name does not appear in the installed typings or upstream source, it does not exist.

## Answer contract

When answering a lightweight-charts question:

1. Name the relevant v5 API.
2. Show one minimal snippet, not a mega-demo.
3. Call out the main foot-gun for that task.
4. Say what local source was checked (version/typings), or state that it could not be verified.
