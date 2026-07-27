import type { TaskAcceptedResponse, TaskStatusResponse } from '../../types/api';

export type ScreenTasksByDate = Record<string, TaskStatusResponse>;

export function acceptedScreenTask(task: TaskAcceptedResponse): TaskStatusResponse {
  return {
    ...task,
    created_at: '',
    updated_at: '',
    logs: []
  };
}

export function isActiveScreenTask(task?: TaskStatusResponse): boolean {
  return Boolean(task && task.status !== 'completed' && task.status !== 'failed');
}

export function upsertScreenTask(
  tasksByDate: ScreenTasksByDate,
  task: TaskStatusResponse
): ScreenTasksByDate {
  const current = tasksByDate[task.trade_date];
  if (
    current?.task_id === task.task_id
    && current.status === task.status
    && current.updated_at === task.updated_at
    && current.progress === task.progress
    && current.progress_label === task.progress_label
  ) {
    return tasksByDate;
  }
  return { ...tasksByDate, [task.trade_date]: task };
}

export function removeScreenTask(
  tasksByDate: ScreenTasksByDate,
  task: Pick<TaskStatusResponse, 'task_id' | 'trade_date'>
): ScreenTasksByDate {
  if (tasksByDate[task.trade_date]?.task_id !== task.task_id) {
    return tasksByDate;
  }
  const next = { ...tasksByDate };
  delete next[task.trade_date];
  return next;
}

export function selectScreenTaskView(
  tasksByDate: ScreenTasksByDate,
  submittingDates: readonly string[],
  selectedTradeDate: string
) {
  const activeTasks = Object.values(tasksByDate)
    .filter(isActiveScreenTask)
    .sort((left, right) => right.trade_date.localeCompare(left.trade_date));
  const selectedTask = activeTasks.find((task) => task.trade_date === selectedTradeDate);
  const backgroundTasks = activeTasks.filter((task) => task.trade_date !== selectedTradeDate);
  const isSubmitting = submittingDates.includes(selectedTradeDate);

  return {
    activeTasks,
    selectedTask,
    backgroundTasks,
    isSubmitting,
    isLoading: isSubmitting || Boolean(selectedTask)
  };
}
