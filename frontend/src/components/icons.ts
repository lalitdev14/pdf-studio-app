import {
  Calendar, Check, CheckCircle2, ChevronDown, ChevronLeft, ChevronRight, Circle, Copy, Download, Eraser,
  FileImage, FilePlus, FileSearch, FileSpreadsheet, FileText, FileType, FileUp, GitCompare, GripVertical, Hash,
  Highlighter, History, Image as ImageIcon, ImageDown, Images, Info, Layers, LayoutGrid, Loader2, Lock, LogOut,
  Maximize, Menu, Merge, MessageSquare, Minimize2, Minus, MousePointer2, PanelBottom, Pencil, Plus, Presentation,
  Redo2, RotateCcw, RotateCw, Save, ScanText, Scissors, Search, Share2, ShieldCheck, Split, Square, Stamp,
  Strikethrough, Trash2, Type, Underline, Undo2, Unlock, Upload, User, Wrench, X, XCircle, ZoomIn, ZoomOut,
  AlertTriangle, ArrowUpRight, PenTool, Sparkles, Scaling, FileArchive, Settings,
} from 'lucide-react';
import type { LucideIcon } from 'lucide-react';

export const ICONS: Record<string, LucideIcon> = {
  image: ImageIcon, imageDown: ImageDown, images: Images, fileText: FileText, sheet: FileSpreadsheet,
  presentation: Presentation, merge: Merge, split: Split, grid: LayoutGrid, rotate: RotateCw, filePlus: FilePlus,
  edit: Pencil, compress: FileArchive, resize: Scaling, stamp: Stamp, eraser: Eraser, hash: Hash,
  headerFooter: PanelBottom, scan: ScanText, textFile: FileType, lock: Lock, unlock: Unlock, signature: PenTool,
  info: Info, layers: Layers, wrench: Wrench, compare: GitCompare, scissors: Scissors, search: FileSearch,
};

export {
  Calendar, Check, CheckCircle2, ChevronDown, ChevronLeft, ChevronRight, Circle, Copy, Download, Eraser,
  FileImage, FileUp, GripVertical, Highlighter, History, Loader2, LogOut, Maximize, Menu, MessageSquare, Minimize2,
  Minus, MousePointer2, Pencil, Plus, Redo2, RotateCcw, RotateCw, Save, Search, Share2, ShieldCheck, Square,
  Strikethrough, Trash2, Type, Underline, Undo2, Upload, User, X, XCircle, ZoomIn, ZoomOut, AlertTriangle,
  ArrowUpRight, PenTool, Sparkles, Settings, FileText, Layers, LayoutGrid, FilePlus, Lock, Unlock, ImageIcon,
};
export type { LucideIcon };
