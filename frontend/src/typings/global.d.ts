// What LazyLibrarian tells the page in index.html, see webapp.py ui_page
interface LazyLibrarianSettings {
  urlBase: string;
  theme: 'dark' | 'light';
  // which libraries are shown
  tabs: { ebook: boolean; audio: boolean; series: boolean; mag: boolean; comic: boolean };
}

interface Window {
  LazyLibrarian: LazyLibrarianSettings;
}

declare module '*.module.css' {
  const classes: Readonly<Record<string, string>>;
  export default classes;
}
