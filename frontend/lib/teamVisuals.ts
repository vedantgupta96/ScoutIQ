type TeamVisual = {
  primary: string;
  secondary: string;
  wash: string;
};

const DEFAULT_VISUAL: TeamVisual = {
  primary: 'var(--accent)',
  secondary: 'var(--confidence)',
  wash: 'rgba(244,98,31,0.12)',
};

const TEAM_VISUALS: Record<string, TeamVisual> = {
  ATL: { primary: '#E03A3E', secondary: '#C1D32F', wash: 'rgba(224,58,62,0.12)' },
  BOS: { primary: '#007A33', secondary: '#BA9653', wash: 'rgba(0,122,51,0.13)' },
  BKN: { primary: '#111111', secondary: '#707782', wash: 'rgba(17,17,17,0.10)' },
  CHA: { primary: '#1D1160', secondary: '#00788C', wash: 'rgba(0,120,140,0.13)' },
  CHI: { primary: '#CE1141', secondary: '#111111', wash: 'rgba(206,17,65,0.12)' },
  CLE: { primary: '#860038', secondary: '#FDBB30', wash: 'rgba(134,0,56,0.12)' },
  DAL: { primary: '#00538C', secondary: '#B8C4CA', wash: 'rgba(0,83,140,0.12)' },
  DEN: { primary: '#0E2240', secondary: '#FEC524', wash: 'rgba(14,34,64,0.12)' },
  DET: { primary: '#C8102E', secondary: '#1D42BA', wash: 'rgba(29,66,186,0.12)' },
  GSW: { primary: '#1D428A', secondary: '#FFC72C', wash: 'rgba(29,66,138,0.13)' },
  HOU: { primary: '#CE1141', secondary: '#C4CED4', wash: 'rgba(206,17,65,0.12)' },
  IND: { primary: '#002D62', secondary: '#FDBB30', wash: 'rgba(0,45,98,0.12)' },
  LAC: { primary: '#C8102E', secondary: '#1D428A', wash: 'rgba(200,16,46,0.12)' },
  LAL: { primary: '#552583', secondary: '#FDB927', wash: 'rgba(85,37,131,0.13)' },
  MEM: { primary: '#5D76A9', secondary: '#12173F', wash: 'rgba(93,118,169,0.14)' },
  MIA: { primary: '#98002E', secondary: '#F9A01B', wash: 'rgba(152,0,46,0.12)' },
  MIL: { primary: '#00471B', secondary: '#EEE1C6', wash: 'rgba(0,71,27,0.13)' },
  MIN: { primary: '#0C2340', secondary: '#78BE20', wash: 'rgba(12,35,64,0.12)' },
  NOP: { primary: '#0C2340', secondary: '#C8102E', wash: 'rgba(12,35,64,0.12)' },
  NYK: { primary: '#006BB6', secondary: '#F58426', wash: 'rgba(0,107,182,0.13)' },
  OKC: { primary: '#007AC1', secondary: '#EF3B24', wash: 'rgba(0,122,193,0.13)' },
  ORL: { primary: '#0077C0', secondary: '#C4CED4', wash: 'rgba(0,119,192,0.13)' },
  PHI: { primary: '#006BB6', secondary: '#ED174C', wash: 'rgba(0,107,182,0.13)' },
  PHX: { primary: '#1D1160', secondary: '#E56020', wash: 'rgba(29,17,96,0.13)' },
  POR: { primary: '#E03A3E', secondary: '#111111', wash: 'rgba(224,58,62,0.12)' },
  SAC: { primary: '#5A2D81', secondary: '#63727A', wash: 'rgba(90,45,129,0.13)' },
  SAS: { primary: '#111111', secondary: '#C4CED4', wash: 'rgba(17,17,17,0.10)' },
  TOR: { primary: '#CE1141', secondary: '#111111', wash: 'rgba(206,17,65,0.12)' },
  UTA: { primary: '#002B5C', secondary: '#F9A01B', wash: 'rgba(0,43,92,0.13)' },
  WAS: { primary: '#002B5C', secondary: '#E31837', wash: 'rgba(0,43,92,0.13)' },
};

export function teamVisual(abbreviation?: string | null): TeamVisual {
  if (!abbreviation) return DEFAULT_VISUAL;
  return TEAM_VISUALS[abbreviation.toUpperCase()] ?? DEFAULT_VISUAL;
}
