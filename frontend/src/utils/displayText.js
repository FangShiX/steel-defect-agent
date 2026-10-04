const SCENE_NAME_MAP = {
  钢铁表面缺陷检测: 'Steel Surface Defect Detection',
}

const DEFECT_NAME_MAP = {
  夹杂: 'Inclusion',
  划痕: 'Scratch',
  裂纹: 'Crack',
  点蚀: 'Pitted surface',
  麻点: 'Pitted surface',
  斑块: 'Patch',
  轧入氧化皮: 'Rolled-in scale',
}

export function displaySceneName(name, isEnglish) {
  if (!isEnglish) return name
  return SCENE_NAME_MAP[name] || name
}

export function displayDefectName(name, isEnglish) {
  if (!isEnglish) return name
  return DEFECT_NAME_MAP[name] || name
}
