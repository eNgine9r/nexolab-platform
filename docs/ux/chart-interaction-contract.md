# Chart interaction contract (#1868)

Every time-series chart (Overview, Live Data, Saved Dashboards, Refrigeration, Energy, Test Sessions) renders through the shared `ChartShell` and `ChartRendererHost` with the ECharts adapter. The same function has the same control, name, place and behaviour everywhere.

| Function              | Control                                                       | Behaviour                                                                                                                                                          |
| --------------------- | ------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Hide or show a series | legend: «Приховати» / «Показати»                              | Hidden series leave the plot, the Y scale (#1843) and the inspector. Identity, colour and history are kept.                                                        |
| Solo                  | legend: «Лише цей»                                            | Shows only this series. Pressing it again on the same series, or «Повернути всі», ends solo.                                                                       |
| Show all              | header: «Повернути всі»                                       | Shown only while a series is hidden. It ends both hide and solo.                                                                                                   |
| Zoom X                | mouse wheel, or a pinch over the plot                         | Immediate native zoom. The window is committed after a short pause, and detail is loaded for it (#1844, #1867).                                                    |
| Pan                   | drag on the plot                                              | The span is kept, and the window is committed on release.                                                                                                          |
| Y scale               | header: «Шкала Y» with «Авто», «Весь період» and «Вручну»     | «Авто» fits the visible window. «Весь період» fits the whole selected period. «Вручну» uses min and max per unit (#1843).                                          |
| Reset zoom            | header: «Скинути масштаб»                                     | Returns to the full selected period, and to Live following when Live was selected.                                                                                 |
| Cursor                | hover, or the keyboard (← → Home End Esc) on the focused plot | The inspector shows the nearest measured value per visible series, or «—» when it is outside tolerance or inside a gap. Linked plots follow the same time (#1866). |
| Export                | header: «Зберегти PNG» where it is supported                  | The visible plot is exported locally.                                                                                                                              |
| Visible interval      | header: «Видимий інтервал»                                    | Shows the interval actually displayed after a zoom or pan.                                                                                                         |

## Line style

- Every analog measurement line is **solid**. Series differ by colour, name and the interactive legend.
- Dashboards saved earlier never stored a line style, so they follow the palette.
- Real gaps stay breaks, and nothing is smoothed or interpolated.

## Justified exceptions

- **Refrigeration controller setpoint:** dashed, because it is a configured reference and not a measurement.
- **Thresholds and events:** dashed or dotted mark lines.
- **Digital state lanes:** step blocks.
- **Saved Dashboards legend:** keeps its search and grouping by instrument, because it holds the most series. Its buttons use the same names («Приховати …», «Лише …»).
