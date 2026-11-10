// Hands files chosen on the home page to the tool page that opens next.
let pending: File[] = [];

export const stash = {
  set(files: File[]) {
    pending = files;
  },
  take(): File[] {
    const f = pending;
    pending = [];
    return f;
  },
};
