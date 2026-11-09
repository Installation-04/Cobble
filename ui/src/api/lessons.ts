import { api } from "./client";

export type LessonSource = "ci_failure" | "loop" | "timeout" | "manual";

/** A short lesson learned inside a project, shown to later agents (ADR 0026). Plain text. */
export interface Lesson {
  id: string;
  text: string;
  source: LessonSource;
  task_ref: string | null;
  active: boolean;
  hits: number;
  created_at: string;
  /** True: the next agent of the project will see it. */
  injected: boolean;
}

export const lessonsApi = {
  list: (id: string) => api.get<Lesson[]>(`/projects/${id}/lessons`),
  add: (id: string, text: string) => api.post<Lesson>(`/projects/${id}/lessons`, { text }),
  update: (id: string, lessonId: string, body: { text?: string; active?: boolean }) =>
    api.patch<Lesson>(`/projects/${id}/lessons/${lessonId}`, body),
  remove: (id: string, lessonId: string) => api.delete(`/projects/${id}/lessons/${lessonId}`),
};
