import type { ThemeMode } from "../theme/store";
import type { Lang } from "../i18n";

export interface User {
  id: string;
  email: string;
  role: "admin";
  lang: Lang;
  theme: ThemeMode;
}

export interface Folder {
  id: string;
  name: string;
  position: number;
}

export interface Project {
  id: string;
  name: string;
  folder_id: string | null;
  created_at: string;
}
