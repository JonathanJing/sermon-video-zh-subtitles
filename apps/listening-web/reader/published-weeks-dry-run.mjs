import { loadPublishedWeeks as loadFormalWeeks } from './published-weeks-base.mjs';
import { loadDryRunWeeks } from './dry-run-app-weeks.mjs';

// Preserve the formal default and append the Dev-only simulation to the App selector.
export async function loadPublishedWeeks(fetchImpl = globalThis.fetch, options = {}) {
  const [formal, simulation] = await Promise.all([
    loadFormalWeeks(fetchImpl, options), loadDryRunWeeks(fetchImpl),
  ]);
  return { weeks: [...simulation.weeks, ...formal.weeks],
    defaultWeekId: formal.defaultWeekId || simulation.defaultWeekId,
    errors: [...formal.errors, ...simulation.errors] };
}
