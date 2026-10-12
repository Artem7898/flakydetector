/** File pickers deliberately show all files. Validate names/sizes after selection.
 * MIME hints vary across Linux/desktop portals and are not a security boundary.
 * The API still validates the actual upload, source bytes and ZIP structure.
 */
export const SOURCE_FILE_LIMIT = 1_000_000;
export const SOURCE_ZIP_LIMIT = 10_000_000;
export const EVENT_FILE_LIMIT = 5_000_000;

function readableSize(file) {
  return Number.isSafeInteger(file?.size) && file.size >= 0;
}

export function sourceFileError(file) {
  const name = typeof file?.name === 'string' ? file.name : '';
  if (!/\.(py|zip)$/i.test(name)) {
    return 'Choose a Python source file (.py) or a ZIP archive (.zip). For a folder, create a ZIP first. Recorder .jsonl files belong in Runtime evidence below.';
  }
  if (!readableSize(file)) return 'Unable to read the selected file size. Select the file again.';
  const zip = /\.zip$/i.test(name);
  if (file.size > (zip ? SOURCE_ZIP_LIMIT : SOURCE_FILE_LIMIT)) {
    return zip ? 'The ZIP exceeds the 10 MB upload limit.' : 'The Python file exceeds the 1 MB upload limit.';
  }
  return null;
}

export function inspectSourceSelection(files) {
  const selected = Array.from(files ?? []);
  // Closing the picker without choosing a replacement preserves the previous file.
  if (selected.length === 0) return {kind: 'cancelled'};
  if (selected.length !== 1) return {kind: 'invalid', error: 'Choose one .py file or one ZIP. To analyze several files, put them in a ZIP archive.'};
  const error = sourceFileError(selected[0]);
  return error ? {kind: 'invalid', error} : {kind: 'selected', file: selected[0]};
}

export function inspectSourceDrop(transfer) {
  const directory = Array.from(transfer?.items ?? []).some(item => item.webkitGetAsEntry?.()?.isDirectory);
  if (directory) return {kind: 'invalid', error: 'Folders cannot be uploaded directly. Create a ZIP of the test folder, then select or drop that ZIP.'};
  const selected = inspectSourceSelection(transfer?.files);
  return selected.kind === 'cancelled'
    ? {kind: 'invalid', error: 'Drop one local .py file or ZIP archive, not a folder or a text link.'}
    : selected;
}

export function sourceUploadEndpoint(file) {
  const error = sourceFileError(file);
  if (error) throw new Error(error);
  return /\.zip$/i.test(file.name) ? '/analyze/directory' : '/analyze/file';
}

export function eventFileError(file) {
  if (typeof file?.name !== 'string' || !/\.jsonl$/i.test(file.name)) {
    return 'This input accepts recorder events (.jsonl), not Python source. To check .py or ZIP files, use File / ZIP in the analysis panel above.';
  }
  if (!readableSize(file)) return 'Unable to read the selected event file size.';
  if (file.size > EVENT_FILE_LIMIT) return 'The event file exceeds the 5 MB upload limit.';
  return null;
}
