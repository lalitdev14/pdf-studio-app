// Catalogue of tools. The generic tool page renders everything from this data, so a
// field's `key` must match the option name of the backend model (app/schemas.py).
import type { ReactNode } from 'react';
import { EXCEL_EXT, IMAGE_EXT, PPT_EXT, WORD_EXT } from './util';

export type Cond = { key: string; in: (string | boolean)[] };
type Base = { key: string; label: string; help?: string; showIf?: Cond };
export type Field =
  | (Base & { type: 'select'; options: { value: string; label: string }[]; default: string; numeric?: boolean })
  | (Base & { type: 'number'; default: number; min?: number; max?: number; step?: number })
  | (Base & { type: 'range'; default: number; min: number; max: number; step: number; unit?: string })
  | (Base & { type: 'text' | 'password' | 'textarea'; default: string; placeholder?: string; sendEmpty?: boolean })
  | (Base & { type: 'checkbox'; default: boolean })
  | (Base & { type: 'color'; default: string })
  | (Base & { type: 'pages'; default: string; placeholder?: string })
  | (Base & { type: 'intlist'; default: string; placeholder?: string });

export type Category = 'Convert' | 'Organize' | 'Edit' | 'Optimize' | 'Secure' | 'Utilities';

export type Tool = {
  id: string;
  title: string;
  short: string;
  description: string;
  icon: string; // key into ICONS (components/icons.ts)
  category: Category;
  endpoint: string;
  accept: 'pdf' | 'image' | 'word' | 'excel' | 'powerpoint';
  minFiles: number;
  maxFiles: number;
  fields: Field[];
  /** merge: let the user pick pages per file */
  perFilePages?: boolean;
  /** `list` -> options.passwords aligned with the files, `single` -> options.password */
  passwords?: 'single' | 'list' | 'none';
  extraFile?: { label: string; accept: 'image' | 'p12'; showIf?: Cond; required: boolean };
  /** name of a 'pages' field that the visual page picker fills in */
  pagePicker?: string;
  confirm?: string; // label of the "I am authorised" checkbox (sets confirm_authorized)
  prefillMetadata?: boolean;
  special?: 'image-to-pdf' | 'organize' | 'editor';
  featureFlag?: 'ocr' | 'office' | 'digital_signature';
  resultNote?: ReactNode;
};

const sel = (key: string, label: string, options: [string, string][], def: string, extra: Partial<Base> & { numeric?: boolean } = {}): Field => ({
  key, label, type: 'select', options: options.map(([value, l]) => ({ value, label: l })), default: def, ...extra,
});
const pages = (key = 'pages', label = 'Pages', def = 'all', extra: Partial<Base> = {}): Field => ({
  key, label, type: 'pages', default: def, placeholder: 'all, or e.g. 1-3,5,8-', ...extra,
});
const POS: [string, string][] = [
  ['bottom-center', 'Bottom centre'], ['bottom-left', 'Bottom left'], ['bottom-right', 'Bottom right'],
  ['top-center', 'Top centre'], ['top-left', 'Top left'], ['top-right', 'Top right'],
];
const FONTS: [string, string][] = [['helvetica', 'Helvetica'], ['times', 'Times'], ['courier', 'Courier']];
const SIZES: [string, string][] = [
  ['a0', 'A0'], ['a1', 'A1'], ['a2', 'A2'], ['a3', 'A3'], ['a4', 'A4'], ['a5', 'A5'],
  ['letter', 'US Letter'], ['legal', 'US Legal'], ['tabloid', 'Tabloid'], ['custom', 'Custom size…'],
];

export const TOOLS: Tool[] = [
  {
    id: 'image-to-pdf', title: 'Image to PDF', short: 'JPG, PNG, WEBP, BMP, TIFF, HEIC → PDF',
    description: 'Combine images into one PDF, or make one PDF per image. Reorder, rotate and choose page size and margins.',
    icon: 'image', category: 'Convert', endpoint: '/api/convert/image-to-pdf', accept: 'image', minFiles: 1, maxFiles: 200,
    fields: [], special: 'image-to-pdf',
  },
  {
    id: 'pdf-to-image', title: 'PDF to Image', short: 'Export pages as PNG, JPG or WEBP',
    description: 'Turn PDF pages into images at 72–600 DPI. Download them one by one or as a ZIP.',
    icon: 'imageDown', category: 'Convert', endpoint: '/api/convert/pdf-to-image', accept: 'pdf', minFiles: 1, maxFiles: 1,
    pagePicker: 'pages', passwords: 'single',
    fields: [
      sel('format', 'Format', [['png', 'PNG (lossless)'], ['jpg', 'JPG'], ['webp', 'WEBP']], 'png'),
      sel('dpi', 'Resolution', [['72', '72 DPI (screen)'], ['150', '150 DPI'], ['300', '300 DPI (print)'], ['600', '600 DPI (very large)']], '150', { numeric: true }),
      { key: 'quality', label: 'Image quality', type: 'range', default: 85, min: 10, max: 100, step: 5, unit: '%', showIf: { key: 'format', in: ['jpg', 'webp'] } },
      pages(),
    ],
  },
  {
    id: 'word-to-pdf', title: 'Word to PDF', short: 'DOCX, DOC, ODT → PDF',
    description: 'Convert Word documents to PDF with LibreOffice.', icon: 'fileText', category: 'Convert',
    endpoint: '/api/convert/office-to-pdf', accept: 'word', minFiles: 1, maxFiles: 1, fields: [], passwords: 'none', featureFlag: 'office',
  },
  {
    id: 'excel-to-pdf', title: 'Excel to PDF', short: 'XLSX, XLS, ODS → PDF',
    description: 'Convert spreadsheets to PDF with LibreOffice.', icon: 'sheet', category: 'Convert',
    endpoint: '/api/convert/office-to-pdf', accept: 'excel', minFiles: 1, maxFiles: 1, fields: [], passwords: 'none', featureFlag: 'office',
  },
  {
    id: 'powerpoint-to-pdf', title: 'PowerPoint to PDF', short: 'PPTX, PPT, ODP → PDF',
    description: 'Convert presentations to PDF with LibreOffice.', icon: 'presentation', category: 'Convert',
    endpoint: '/api/convert/office-to-pdf', accept: 'powerpoint', minFiles: 1, maxFiles: 1, fields: [], passwords: 'none', featureFlag: 'office',
  },
  {
    id: 'pdf-to-word', title: 'PDF to Word', short: 'Rebuild the text as a DOCX',
    description: 'Extracts the text into an editable Word file. Fonts and layout are not preserved; scanned pages are inserted as pictures.',
    icon: 'fileText', category: 'Convert', endpoint: '/api/convert/pdf-to-word', accept: 'pdf', minFiles: 1, maxFiles: 1, passwords: 'single', fields: [],
  },
  {
    id: 'pdf-to-excel', title: 'PDF to Excel', short: 'Tables become worksheets',
    description: 'Detects tables and writes each one to its own sheet. If no tables are found, the text is placed line by line.',
    icon: 'sheet', category: 'Convert', endpoint: '/api/convert/pdf-to-excel', accept: 'pdf', minFiles: 1, maxFiles: 1, passwords: 'single', fields: [],
  },
  {
    id: 'pdf-to-powerpoint', title: 'PDF to PowerPoint', short: 'One slide per page',
    description: 'Creates one slide per page, either as a picture of the page or as editable text.',
    icon: 'presentation', category: 'Convert', endpoint: '/api/convert/pdf-to-powerpoint', accept: 'pdf', minFiles: 1, maxFiles: 1, passwords: 'single',
    fields: [sel('mode', 'Slide content', [['image', 'Picture of each page (looks identical)'], ['text', 'Editable text only']], 'image')],
  },
  {
    id: 'merge', title: 'Merge PDF', short: 'Combine PDFs into one',
    description: 'Combine several PDFs into one document. Reorder files and choose which pages of each to include.',
    icon: 'merge', category: 'Organize', endpoint: '/api/pdf/merge', accept: 'pdf', minFiles: 2, maxFiles: 50, perFilePages: true, passwords: 'list', fields: [],
  },
  {
    id: 'split', title: 'Split PDF', short: 'Extract pages or split into files',
    description: 'Split by ranges, into single pages, into equal groups, or extract odd/even or hand-picked pages.',
    icon: 'split', category: 'Organize', endpoint: '/api/pdf/split', accept: 'pdf', minFiles: 1, maxFiles: 1, pagePicker: 'pages', passwords: 'single',
    fields: [
      sel('mode', 'Split mode', [['ranges', 'By page ranges (one file per range)'], ['every', 'Every page into its own file'], ['groups', 'Equal groups of pages'], ['odd', 'Odd pages only'], ['even', 'Even pages only'], ['extract', 'Extract selected pages into one file']], 'ranges'),
      { key: 'ranges', label: 'Ranges', type: 'text', default: '', placeholder: '1-3,4-6,9', help: 'Each comma-separated part becomes its own PDF.', showIf: { key: 'mode', in: ['ranges'] } },
      pages('pages', 'Pages to extract', '', { showIf: { key: 'mode', in: ['extract'] } }),
      { key: 'group_size', label: 'Pages per file', type: 'number', default: 2, min: 1, max: 1000, showIf: { key: 'mode', in: ['groups'] } },
    ],
  },
  {
    id: 'organize', title: 'Organize PDF', short: 'Reorder, rotate, delete, duplicate pages',
    description: 'A visual page manager: drag to reorder, rotate, delete, duplicate, extract and insert pages from another PDF.',
    icon: 'grid', category: 'Organize', endpoint: '/api/pdf/organize', accept: 'pdf', minFiles: 1, maxFiles: 21, fields: [], special: 'organize',
  },
  {
    id: 'rotate', title: 'Rotate PDF', short: 'Rotate all or selected pages',
    description: 'Rotate every page, or only the pages you pick, by 90°, 180° or 270°.',
    icon: 'rotate', category: 'Organize', endpoint: '/api/pdf/rotate', accept: 'pdf', minFiles: 1, maxFiles: 1, pagePicker: 'pages', passwords: 'single',
    fields: [sel('angle', 'Rotate clockwise by', [['90', '90°'], ['180', '180°'], ['270', '270° (90° counter-clockwise)']], '90', { numeric: true }), pages()],
  },
  {
    id: 'blank-pages', title: 'Add blank pages', short: 'Insert empty pages anywhere',
    description: 'Insert blank pages at the start, end or after any page.',
    icon: 'filePlus', category: 'Organize', endpoint: '/api/pdf/blank-pages', accept: 'pdf', minFiles: 1, maxFiles: 1, passwords: 'single',
    fields: [
      { key: 'positions', label: 'Insert after page(s)', type: 'intlist', default: '0', placeholder: '0, 3, 10', help: '0 inserts before the first page. Use the page count to add at the end.' },
      { key: 'count', label: 'Blank pages at each position', type: 'number', default: 1, min: 1, max: 50 },
      sel('size', 'Page size', [['match', 'Same as neighbouring page'], ['a4', 'A4'], ['letter', 'US Letter']], 'match'),
    ],
  },
  {
    id: 'edit', title: 'PDF Editor', short: 'Annotate, add text, draw, sign',
    description: 'Open a document in the full editing workspace: text, highlights, drawing, shapes, images, signatures and more.',
    icon: 'edit', category: 'Edit', endpoint: '/api/pdf/edit', accept: 'pdf', minFiles: 1, maxFiles: 1, fields: [], special: 'editor',
  },
  {
    id: 'compress', title: 'Compress PDF', short: 'Reduce file size',
    description: 'Shrinks images and optimises the file structure. If nothing can be saved, you are told so and get your original back.',
    icon: 'compress', category: 'Optimize', endpoint: '/api/pdf/compress', accept: 'pdf', minFiles: 1, maxFiles: 1, passwords: 'single',
    fields: [
      sel('level', 'Compression level', [['low', 'Low – best quality, modest savings'], ['recommended', 'Recommended – balanced'], ['high', 'High – smallest file, lower image quality']], 'recommended'),
      { key: 'strip_metadata', label: 'Remove thumbnails and extra metadata', type: 'checkbox', default: true },
    ],
  },
  {
    id: 'resize', title: 'Resize PDF', short: 'Change page size (A4, Letter, custom…)',
    description: 'Scale the content onto a new page size, keeping proportions, with optional margins. Resize all pages or just some.',
    icon: 'resize', category: 'Optimize', endpoint: '/api/pdf/resize', accept: 'pdf', minFiles: 1, maxFiles: 1, pagePicker: 'pages', passwords: 'single',
    fields: [
      sel('size', 'Page size', SIZES, 'a4'),
      { key: 'custom_width_mm', label: 'Width (mm)', type: 'number', default: 210, min: 10, max: 5000, showIf: { key: 'size', in: ['custom'] } },
      { key: 'custom_height_mm', label: 'Height (mm)', type: 'number', default: 297, min: 10, max: 5000, showIf: { key: 'size', in: ['custom'] } },
      sel('orientation', 'Orientation', [['auto', 'Keep each page’s orientation'], ['portrait', 'Portrait'], ['landscape', 'Landscape']], 'auto'),
      sel('mode', 'Scaling', [['fit', 'Fit inside page (keep proportions)'], ['fill', 'Fill page (crop the overflow)'], ['stretch', 'Stretch to page (distorts)']], 'fit'),
      { key: 'margin_mm', label: 'Margin (mm)', type: 'number', default: 0, min: 0, max: 100 },
      pages(),
    ],
  },
  {
    id: 'watermark', title: 'Add watermark', short: 'Text or image watermark',
    description: 'Stamp text or a logo across pages, centred or tiled, over or under the content.',
    icon: 'stamp', category: 'Edit', endpoint: '/api/pdf/watermark', accept: 'pdf', minFiles: 1, maxFiles: 2, passwords: 'single',
    extraFile: { label: 'Watermark image (PNG with transparency works best)', accept: 'image', showIf: { key: 'kind', in: ['image'] }, required: true },
    fields: [
      sel('kind', 'Watermark type', [['text', 'Text'], ['image', 'Image']], 'text'),
      { key: 'text', label: 'Text', type: 'text', default: 'CONFIDENTIAL', showIf: { key: 'kind', in: ['text'] } },
      { key: 'font_size', label: 'Font size (pt)', type: 'number', default: 64, min: 6, max: 400, showIf: { key: 'kind', in: ['text'] } },
      { key: 'color', label: 'Colour', type: 'color', default: '#888888', showIf: { key: 'kind', in: ['text'] } },
      { key: 'image_scale_pct', label: 'Image width', type: 'range', default: 50, min: 5, max: 100, step: 5, unit: '% of page', showIf: { key: 'kind', in: ['image'] } },
      { key: 'opacity', label: 'Opacity', type: 'range', default: 0.25, min: 0.05, max: 1, step: 0.05 },
      { key: 'rotation', label: 'Rotation (°)', type: 'number', default: 45, min: -180, max: 180 },
      sel('position', 'Placement', [['center', 'Centred'], ['tile', 'Tiled across the page']], 'center'),
      sel('layer', 'Layer', [['over', 'On top of content'], ['under', 'Behind content']], 'over'),
      pages(),
    ],
  },
  {
    id: 'remove-watermark', title: 'Remove watermark', short: 'Remove tagged watermarks',
    description: 'Removes watermarks that are tagged as artifacts (such as those added here or by Acrobat). Watermarks baked into images or page content cannot be separated and will not be touched.',
    icon: 'eraser', category: 'Edit', endpoint: '/api/pdf/remove-watermark', accept: 'pdf', minFiles: 1, maxFiles: 1, passwords: 'single',
    confirm: 'I own this document or am authorised to remove its watermark.', fields: [pages()],
  },
  {
    id: 'page-numbers', title: 'Add page numbers', short: 'Number the pages',
    description: 'Add page numbers in any corner or centre, with custom text such as “Page {n} of {total}”.',
    icon: 'hash', category: 'Edit', endpoint: '/api/pdf/page-numbers', accept: 'pdf', minFiles: 1, maxFiles: 1, passwords: 'single',
    fields: [
      { key: 'format', label: 'Text', type: 'text', default: 'Page {n} of {total}', help: '{n} = page number, {total} = page count' },
      sel('position', 'Position', POS, 'bottom-center'),
      { key: 'start_at', label: 'First page is numbered', type: 'number', default: 1, min: -999, max: 99999, help: 'Set 0 with “skip first page” to start the second page at 1.' },
      { key: 'skip_first', label: 'Skip the first page', type: 'checkbox', default: false },
      sel('font', 'Font', FONTS, 'helvetica'),
      { key: 'font_size', label: 'Size (pt)', type: 'number', default: 10, min: 4, max: 72 },
      { key: 'color', label: 'Colour', type: 'color', default: '#333333' },
      { key: 'margin_pt', label: 'Distance from edge (pt)', type: 'number', default: 28, min: 0, max: 200 },
      pages(),
    ],
  },
  {
    id: 'header-footer', title: 'Headers & footers', short: 'Add running text to every page',
    description: 'Add text to the top and bottom of pages. Tokens: {n} page, {total} page count, {date}, {filename}.',
    icon: 'headerFooter', category: 'Edit', endpoint: '/api/pdf/header-footer', accept: 'pdf', minFiles: 1, maxFiles: 1, passwords: 'single',
    fields: [
      { key: 'header_left', label: 'Header – left', type: 'text', default: '' },
      { key: 'header_center', label: 'Header – centre', type: 'text', default: '' },
      { key: 'header_right', label: 'Header – right', type: 'text', default: '' },
      { key: 'footer_left', label: 'Footer – left', type: 'text', default: '' },
      { key: 'footer_center', label: 'Footer – centre', type: 'text', default: '' },
      { key: 'footer_right', label: 'Footer – right', type: 'text', default: '{n} / {total}' },
      sel('font', 'Font', FONTS, 'helvetica'),
      { key: 'font_size', label: 'Size (pt)', type: 'number', default: 10, min: 4, max: 72 },
      { key: 'color', label: 'Colour', type: 'color', default: '#333333' },
      { key: 'margin_pt', label: 'Distance from edge (pt)', type: 'number', default: 28, min: 0, max: 200 },
      { key: 'skip_first', label: 'Skip the first page', type: 'checkbox', default: false },
      pages(),
    ],
  },
  {
    id: 'ocr', title: 'OCR – make searchable', short: 'Recognise text in scanned PDFs',
    description: 'Runs Tesseract OCR on scanned pages and adds an invisible text layer so the PDF becomes searchable and copyable.',
    icon: 'scan', category: 'Utilities', endpoint: '/api/pdf/ocr', accept: 'pdf', minFiles: 1, maxFiles: 1, passwords: 'single', featureFlag: 'ocr',
    fields: [
      { key: 'lang', label: 'Language(s)', type: 'text', default: 'eng', help: 'Tesseract codes joined with +, e.g. eng+deu. Only languages installed on the server work.' },
      sel('dpi', 'Scan resolution', [['200', '200 DPI (faster)'], ['300', '300 DPI (recommended)'], ['400', '400 DPI (small print)']], '300', { numeric: true }),
      { key: 'skip_text_pages', label: 'Skip pages that already have text', type: 'checkbox', default: true },
      sel('output', 'Output', [['pdf', 'Searchable PDF'], ['txt', 'Text file'], ['both', 'Both']], 'pdf'),
      pages(),
    ],
  },
  {
    id: 'extract-text', title: 'Extract text', short: 'Get the text out as .txt',
    description: 'Extracts the text layer of every page. Pages without text (scans) are reported; optionally OCR them.',
    icon: 'textFile', category: 'Utilities', endpoint: '/api/pdf/extract-text', accept: 'pdf', minFiles: 1, maxFiles: 1, pagePicker: 'pages', passwords: 'single',
    fields: [
      pages(),
      { key: 'layout', label: 'Keep the visual layout (columns, spacing)', type: 'checkbox', default: true },
      { key: 'ocr_fallback', label: 'Run OCR on pages without text', type: 'checkbox', default: false },
      { key: 'ocr_lang', label: 'OCR language', type: 'text', default: 'eng', showIf: { key: 'ocr_fallback', in: [true] } },
    ],
  },
  {
    id: 'extract-images', title: 'Extract images', short: 'Save embedded pictures',
    description: 'Saves every image embedded in the PDF in its original quality.',
    icon: 'images', category: 'Utilities', endpoint: '/api/pdf/extract-images', accept: 'pdf', minFiles: 1, maxFiles: 1, passwords: 'single', fields: [],
  },
  {
    id: 'protect', title: 'Protect PDF', short: 'Password-protect with AES-256',
    description: 'Encrypts the PDF with AES-256. Optionally restrict printing, copying and editing (needs an owner password).',
    icon: 'lock', category: 'Secure', endpoint: '/api/pdf/protect', accept: 'pdf', minFiles: 1, maxFiles: 1, passwords: 'single',
    fields: [
      { key: 'user_password', label: 'Password to open the file', type: 'password', default: '' },
      { key: 'owner_password', label: 'Owner password (to lift restrictions)', type: 'password', default: '', help: 'Required if you turn off any permission below. Keep it safe – it cannot be recovered.' },
      { key: 'allow_print', label: 'Allow printing', type: 'checkbox', default: true },
      { key: 'allow_copy', label: 'Allow copying text and images', type: 'checkbox', default: true },
      { key: 'allow_edit', label: 'Allow editing and annotating', type: 'checkbox', default: true },
    ],
  },
  {
    id: 'unlock', title: 'Unlock PDF', short: 'Remove a password you know',
    description: 'Removes the password from a PDF. You must enter the correct password; PDF Studio never tries to bypass or guess passwords.',
    icon: 'unlock', category: 'Secure', endpoint: '/api/pdf/unlock', accept: 'pdf', minFiles: 1, maxFiles: 1, passwords: 'single',
    confirm: 'I am authorised to remove this PDF’s password.', fields: [],
  },
  {
    id: 'sign', title: 'Digital signature', short: 'Sign with a .p12 / .pfx certificate',
    description: 'Adds a cryptographic signature using your certificate. (For a drawn or image signature, use the PDF Editor.)',
    icon: 'signature', category: 'Secure', endpoint: '/api/pdf/sign', accept: 'pdf', minFiles: 2, maxFiles: 2, passwords: 'single', featureFlag: 'digital_signature',
    extraFile: { label: 'Certificate (.p12 or .pfx)', accept: 'p12', required: true },
    fields: [
      { key: 'p12_password', label: 'Certificate password', type: 'password', default: '' },
      { key: 'reason', label: 'Reason (optional)', type: 'text', default: '' },
      { key: 'location', label: 'Location (optional)', type: 'text', default: '' },
    ],
  },
  {
    id: 'metadata', title: 'Edit metadata', short: 'Title, author, keywords…',
    description: 'View and edit document properties, or clear them all.',
    icon: 'info', category: 'Utilities', endpoint: '/api/pdf/metadata', accept: 'pdf', minFiles: 1, maxFiles: 1, passwords: 'single', prefillMetadata: true,
    fields: [
      { key: 'title', label: 'Title', type: 'text', default: '', sendEmpty: true },
      { key: 'author', label: 'Author', type: 'text', default: '', sendEmpty: true },
      { key: 'subject', label: 'Subject', type: 'text', default: '', sendEmpty: true },
      { key: 'keywords', label: 'Keywords', type: 'text', default: '', sendEmpty: true },
      { key: 'creator', label: 'Creator', type: 'text', default: '', sendEmpty: true },
      { key: 'producer', label: 'Producer', type: 'text', default: '', sendEmpty: true },
      { key: 'clear_all', label: 'Remove all metadata', type: 'checkbox', default: false },
    ],
  },
  {
    id: 'flatten', title: 'Flatten PDF', short: 'Bake in form fields and annotations',
    description: 'Turns form fields and annotations into fixed page content so they can no longer be edited.',
    icon: 'layers', category: 'Utilities', endpoint: '/api/pdf/flatten', accept: 'pdf', minFiles: 1, maxFiles: 1, passwords: 'single',
    fields: [sel('mode', 'What to flatten', [['all', 'Everything'], ['screen', 'What shows on screen'], ['print', 'What prints']], 'all')],
  },
  {
    id: 'repair', title: 'Repair PDF', short: 'Recover a damaged file',
    description: 'Rebuilds broken cross-reference tables and structures. It cannot restore data that is truly missing.',
    icon: 'wrench', category: 'Utilities', endpoint: '/api/pdf/repair', accept: 'pdf', minFiles: 1, maxFiles: 1, passwords: 'none', fields: [],
  },
  {
    id: 'compare', title: 'Compare PDFs', short: 'Find the differences',
    description: 'Compares two PDFs page by page, highlights visual changes in red and lists text differences.',
    icon: 'compare', category: 'Utilities', endpoint: '/api/pdf/compare', accept: 'pdf', minFiles: 2, maxFiles: 2, passwords: 'list',
    fields: [{ key: 'sensitivity', label: 'Sensitivity', type: 'range', default: 40, min: 5, max: 200, step: 5, help: 'Lower = notices smaller changes' }],
  },
];

export const TOOL_BY_ID: Record<string, Tool> = Object.fromEntries(TOOLS.map((t) => [t.id, t]));
export const CATEGORIES: Category[] = ['Convert', 'Organize', 'Edit', 'Optimize', 'Secure', 'Utilities'];

export function toolPath(t: Tool): string {
  return t.special === 'editor' ? '/editor' : `/tools/${t.id}`;
}

export function acceptExt(kind: Tool['accept'] | 'p12'): string[] {
  switch (kind) {
    case 'pdf': return ['pdf'];
    case 'image': return IMAGE_EXT;
    case 'word': return WORD_EXT;
    case 'excel': return EXCEL_EXT;
    case 'powerpoint': return PPT_EXT;
    case 'p12': return ['p12', 'pfx'];
  }
}

export function condMet(c: Cond | undefined, values: Record<string, unknown>): boolean {
  if (!c) return true;
  return c.in.includes(values[c.key] as string | boolean);
}
