// Цветовые карты для уровней риска, статусов, типов цели и статусов транзакций.
export const RISK = {
  high:   {color:'#ff6f6f', bg:'rgba(255,90,90,.13)'},
  medium: {color:'#f5b54a', bg:'rgba(245,170,60,.14)'},
  low:    {color:'#34d399', bg:'rgba(52,211,153,.13)'},
};
export const STAT = {
  open:           {color:'#f5b54a', bg:'rgba(245,170,60,.13)'},
  in_progress:    {color:'#5fded0', bg:'rgba(95,222,208,.14)'},
  closed:         {color:'#34d399', bg:'rgba(52,211,153,.13)'},
  false_positive: {color:'#9aa3b2', bg:'rgba(150,160,180,.13)'},
};
export const TYPE = {
  tx:  {label:'TX',  color:'#5fded0', bg:'rgba(95,222,208,.14)'},
  wlt: {label:'WLT', color:'#a5b4fc', bg:'rgba(129,140,248,.16)'},
};
export const TXSTAT = {
  success: {c:'#34d399', b:'rgba(52,211,153,.13)'},
  pending: {c:'#f5b54a', b:'rgba(245,170,60,.13)'},
  failed:  {c:'#ff6f6f', b:'rgba(255,90,90,.13)'},
};
