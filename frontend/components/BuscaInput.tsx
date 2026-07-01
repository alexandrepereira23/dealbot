"use client";

type Props = {
  valor: string;
  onChange: (v: string) => void;
  placeholder?: string;
};

export function BuscaInput({ valor, onChange, placeholder }: Props) {
  return (
    <div className="busca">
      <input
        type="search"
        className="busca__input"
        value={valor}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder ?? "Buscar (ex: acer, cupom, rtx)"}
        autoComplete="off"
        spellCheck={false}
      />
      {valor && (
        <button
          type="button"
          className="busca__clear"
          onClick={() => onChange("")}
          aria-label="Limpar busca"
        >
          ×
        </button>
      )}
    </div>
  );
}
