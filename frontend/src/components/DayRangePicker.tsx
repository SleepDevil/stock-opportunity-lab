import { useEffect, useMemo, useState } from 'react';
import { Badge, Button, Group, Popover, Text } from '@mantine/core';
import { DatePicker } from '@mantine/dates';
import { CalendarDays } from 'lucide-react';

import {
  completeInputDateRange,
  formatInputDateRange,
  makeSingleInputDateRange,
  makeStockAnalysisDateRangePresets,
  normalizeInputDateRange,
  type InputDateRange,
  type InputDateRangePreset
} from '../lib/dateRange';
import { todayInputValue } from '../lib/format';

function sameRange(a: InputDateRange, b: InputDateRange): boolean {
  const [aStart, aEnd] = normalizeInputDateRange(a);
  const [bStart, bEnd] = normalizeInputDateRange(b);
  return aStart === bStart && aEnd === bEnd;
}

export function DayRangePicker({
  label = '日期区间',
  value,
  onChange,
  today = todayInputValue(),
  presets,
  className
}: {
  label?: string;
  value: InputDateRange;
  onChange: (value: InputDateRange) => void;
  today?: string;
  presets?: InputDateRangePreset[];
  className?: string;
}) {
  const normalizedValue = useMemo(
    () => normalizeInputDateRange(value),
    [value[0], value[1]]
  );
  const presetOptions = useMemo(() => presets ?? makeStockAnalysisDateRangePresets(today), [presets, today]);
  const [opened, setOpened] = useState(false);
  const [draftRange, setDraftRange] = useState<InputDateRange>(normalizedValue);
  const [calendarDate, setCalendarDate] = useState<string>(normalizedValue[1] ?? normalizedValue[0] ?? today);

  useEffect(() => {
    if (!opened) {
      setDraftRange(normalizedValue);
      setCalendarDate(normalizedValue[1] ?? normalizedValue[0] ?? today);
    }
  }, [normalizedValue, opened, today]);

  function updateDraft(next: InputDateRange) {
    const normalizedNext = normalizeInputDateRange(next);
    setDraftRange(normalizedNext);
    setCalendarDate(normalizedNext[1] ?? normalizedNext[0] ?? today);
  }

  function applyRange(next: InputDateRange) {
    const completed = completeInputDateRange(next, today);
    onChange(completed);
    setDraftRange(completed);
    setCalendarDate(completed[1] ?? completed[0] ?? today);
    setOpened(false);
  }

  function resetDraftAndClose() {
    setDraftRange(normalizedValue);
    setCalendarDate(normalizedValue[1] ?? normalizedValue[0] ?? today);
    setOpened(false);
  }

  const activeLabel = formatInputDateRange(normalizedValue);
  const draftLabel = formatInputDateRange(completeInputDateRange(draftRange, today));

  return (
    <Popover
      opened={opened}
      onChange={setOpened}
      position="bottom-start"
      width={820}
      radius="md"
      shadow="xl"
      offset={8}
      withinPortal
      trapFocus
    >
      <Popover.Target>
        <button
          type="button"
          className={`day-range-trigger ${className ?? ''}`}
          aria-label={`${label}: ${activeLabel}`}
          onClick={() => setOpened((current) => !current)}
        >
          <span className="day-range-trigger-label">{label}</span>
          <span className="day-range-trigger-value">
            <CalendarDays size={15} />
            {activeLabel}
          </span>
        </button>
      </Popover.Target>
      <Popover.Dropdown className="day-range-popover">
        <div className="day-range-panel">
          <div className="day-range-presets">
            {presetOptions.map((preset) => (
              <button
                key={preset.label}
                type="button"
                className={sameRange(draftRange, preset.range) ? 'active' : ''}
                onClick={() => updateDraft(preset.range)}
              >
                <span>{preset.label}</span>
                {preset.recommended ? <em>推荐</em> : null}
              </button>
            ))}
          </div>
          <div className="day-range-calendar-shell">
            <Group justify="space-between" mb="xs" align="center">
              <div>
                <Text size="sm" fw={900}>天级范围</Text>
                <Text size="xs" c="dimmed">{draftLabel}</Text>
              </div>
              <Badge variant="light" color="blue">天级</Badge>
            </Group>
            <DatePicker
              type="range"
              value={draftRange}
              onChange={updateDraft}
              date={calendarDate}
              onDateChange={setCalendarDate}
              allowSingleDateInRange
              numberOfColumns={2}
              columnsToScroll={1}
              locale="zh-cn"
              firstDayOfWeek={0}
              maxLevel="year"
              highlightToday
            />
            <Group justify="space-between" mt="md">
              <Button variant="subtle" color="blue" onClick={() => updateDraft(makeSingleInputDateRange(today))}>
                今天
              </Button>
              <Group gap="xs">
                <Button variant="default" onClick={resetDraftAndClose}>
                  取消
                </Button>
                <Button onClick={() => applyRange(draftRange)}>
                  确定
                </Button>
              </Group>
            </Group>
          </div>
        </div>
      </Popover.Dropdown>
    </Popover>
  );
}
