import React, { ReactNode } from "react";

// Props for Table
interface TableProps {
  children: ReactNode; // Table content (thead, tbody, etc.)
  className?: string; // Optional className for styling
  fixed?: boolean; // lay out columns from the header, never from content width
}

// Props for TableHeader
interface TableHeaderProps {
  children: ReactNode; // Header row(s)
  className?: string; // Optional className for styling
}

// Props for TableBody
interface TableBodyProps {
  children: ReactNode; // Body row(s)
  className?: string; // Optional className for styling
}

// Props for TableRow
interface TableRowProps {
  children: ReactNode; // Cells (th or td)
  className?: string; // Optional className for styling
  onClick?: () => void; // Optional click handler (row-as-button tables)
}

// Props for TableCell
interface TableCellProps {
  children: ReactNode; // Cell content
  isHeader?: boolean; // If true, renders as <th>, otherwise <td>
  className?: string; // Optional className for styling
  style?: React.CSSProperties; // column widths for fixed-layout tables
  onClick?: () => void; // sortable headers: the click that reorders
  title?: string; // hover hint, e.g. "sort by win %"
}

// Table Component
const Table: React.FC<TableProps> = ({ children, className, fixed }) => {
  // `fixed` keeps a wide table inside the viewport: the Auto Trade screen must
  // not scroll sideways, and min-w-full + auto layout is what made it.
  return (
    <table className={`w-full ${fixed ? "table-fixed" : "min-w-full"} ${className ?? ""}`}>
      {children}
    </table>
  );
};

// TableHeader Component
const TableHeader: React.FC<TableHeaderProps> = ({ children, className }) => {
  return <thead className={className}>{children}</thead>;
};

// TableBody Component
const TableBody: React.FC<TableBodyProps> = ({ children, className }) => {
  return <tbody className={className}>{children}</tbody>;
};

// TableRow Component
const TableRow: React.FC<TableRowProps> = ({ children, className, onClick }) => {
  return (
    <tr className={className} onClick={onClick}>
      {children}
    </tr>
  );
};

// TableCell Component
const TableCell: React.FC<TableCellProps> = ({
  children,
  isHeader = false,
  className,
  style,
  onClick,
  title,
}) => {
  const CellTag = isHeader ? "th" : "td";
  // break-words + align-top: a fixed-layout table must be allowed to wrap,
  // or one long cell pushes the whole screen sideways.
  return (
    <CellTag style={style} onClick={onClick} title={title}
      className={`align-top break-words ${className ?? ""}`}>
      {children}
    </CellTag>
  );
};

export { Table, TableHeader, TableBody, TableRow, TableCell };
