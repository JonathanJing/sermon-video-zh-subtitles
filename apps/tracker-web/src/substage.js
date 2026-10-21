const UNIT_SUBSTAGES = new Set(['unit_synthesis', 'audio_validation']);

export function substageProgressLabel(id, completedUnits, totalUnits, language = 'zh') {
  const completed = Number.isFinite(completedUnits) && completedUnits >= 0 ? completedUnits : 0;
  if (!Number.isInteger(totalUnits) || totalUnits < 0) {
    return language === 'en' ? `${completed} completed` : `${completed} 次完成`;
  }
  const count = `${Math.min(completed, totalUnits)}/${totalUnits}`;
  if (UNIT_SUBSTAGES.has(id)) {
    return language === 'en' ? `${count} units` : `${count} 单元`;
  }
  return language === 'en' ? `${count} groups` : `${count} 组`;
}
