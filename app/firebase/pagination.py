"""Paginação limitada por push ID, sem depender da ordem do JSON."""

import re


def validate_key(key):
    if not isinstance(key, str) or not re.fullmatch(r"[-0-9A-Z_a-z]{20}", key):
        raise ValueError("A origem deve usar push IDs Firebase de 20 caracteres.")
    return key


def read_result(query, limit):
    result = query.get()
    if result is None:
        return {}
    if not isinstance(result, dict) or len(result) > limit:
        raise ValueError("Resposta Firebase inválida ou acima do limite.")
    for key in result:
        validate_key(key)
    return dict(sorted(result.items()))


def last_key(reference):
    result = read_result(reference.order_by_key().limit_to_last(1), 1)
    return max(result) if result else None


def window_start(reference, checkpoint, count, page_size=500):
    validate_key(checkpoint)
    if count < 0 or page_size < 1:
        raise ValueError("Janela deve ser não negativa e página positiva.")
    lower = None
    remaining = count
    while remaining:
        boundary = lower if lower is not None else checkpoint
        size = min(page_size, remaining)
        limit = size + int(lower is not None)
        result = read_result(
            reference.order_by_key().end_at(boundary).limit_to_last(limit), limit,
        )
        if any(key > boundary for key in result):
            raise RuntimeError("Firebase ignorou o limite superior.")
        candidates = [key for key in result if lower is None or key < lower]
        if not candidates:
            break
        selected = candidates[-size:]
        lower = min(selected)
        remaining -= len(selected)
        if len(selected) < size:
            break
    return lower


def iter_pages(reference, page_size, *, after=None, start=None, end=None):
    """Fronteira inclusiva no RTDB; exclusão local só após emitir a página."""
    if page_size < 1:
        raise ValueError("Tamanho da página deve ser positivo.")
    for key in (after, start, end):
        if key is not None:
            validate_key(key)
    cursor = after
    while end is None or cursor is None or cursor < end:
        lower = cursor if cursor is not None else start
        query = reference.order_by_key()
        if lower is not None:
            query = query.start_at(lower)
        if end is not None:
            query = query.end_at(end)
        limit = page_size + int(cursor is not None)
        raw = read_result(query.limit_to_first(limit), limit)
        if not raw:
            return
        if any((lower is not None and key < lower) or
               (end is not None and key > end) for key in raw):
            raise RuntimeError("Página fora dos limites; possível repetição.")
        page = {key: value for key, value in raw.items()
                if cursor is None or key > cursor}
        if not page:
            # Uma única fronteira é o término normal sem horizonte explícito.
            if len(raw) == 1 and cursor in raw:
                return
            raise RuntimeError("Página sem avanço.")
        # Se a fronteira foi excluída na origem, preservar o item excedente
        # para a próxima consulta, em vez de saltá-lo.
        page = dict(list(page.items())[:page_size])
        yield page
        cursor = max(page)
        if len(page) < page_size:
            return
