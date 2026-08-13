export type NullableCurvePoint = Record<string, number | string | boolean | null | undefined>;
export type ChartPlot = { left: number; right: number; top: number; bottom: number };
export type ChartDomain = { min: number; max: number };

export function chartX(index: number, count: number, width: number, plot: ChartPlot): number {
  return plot.left + (count <= 1 ? 0 : (index / (count - 1)) * (width - plot.left - plot.right));
}

export function chartY(value: number, height: number, plot: ChartPlot, domain: ChartDomain): number {
  const ratio = (value - domain.min) / (domain.max - domain.min || 1);
  return height - plot.bottom - ratio * (height - plot.top - plot.bottom);
}

export function pathForNullableSeries(
  points: NullableCurvePoint[],
  key: string,
  width: number,
  height: number,
  plot: ChartPlot,
  domain: ChartDomain,
): string {
  const commands: string[] = [];
  let segmentOpen = false;
  for (const [index, point] of points.entries()) {
    const value = point[key];
    if (typeof value !== 'number' || !Number.isFinite(value)) {
      segmentOpen = false;
      continue;
    }
    const command = segmentOpen ? 'L' : 'M';
    commands.push(`${command}${chartX(index, points.length, width, plot).toFixed(2)},${chartY(value, height, plot, domain).toFixed(2)}`);
    segmentOpen = true;
  }
  return commands.join(' ');
}
