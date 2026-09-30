package contracts

import (
	"encoding/json"
	"errors"
	"fmt"
)

// ErrInvalidPagination means a pagination request violates the contract.
var ErrInvalidPagination = errors.New("invalid canonical pagination")

// Pagination bounds mirror pagination.schema.json.
const (
	// MinPageLimit and MaxPageLimit bound the limit. The schema maximum is 500.
	MinPageLimit int32 = 1
	MaxPageLimit int32 = 500
	// DefaultPageLimit is the schema default for an absent limit.
	DefaultPageLimit int32 = 100
	// MaxCursorLength is the schema maxLength for the opaque cursor.
	MaxCursorLength = 512
)

// SortOrder is the closed set of sort directions.
type SortOrder string

// The permitted sort orders.
const (
	OrderAscending  SortOrder = "asc"
	OrderDescending SortOrder = "desc"
)

// Valid reports whether the order is in the closed set.
func (o SortOrder) Valid() bool {
	return o == OrderAscending || o == OrderDescending
}

// String returns the wire form.
func (o SortOrder) String() string { return string(o) }

// ParseSortOrder resolves a sort direction, rejecting anything outside the closed set.
func ParseSortOrder(s string) (SortOrder, error) {
	o := SortOrder(s)
	if !o.Valid() {
		return "", fmt.Errorf(
			"%w: %q is not a known sort order; unknown values are unsupported, not mapped to a default",
			ErrInvalidPagination, s,
		)
	}
	return o, nil
}

// Pagination is a cursor-based page request.
//
// Cursor, never offset. pagination.schema.json states that an offset over a mutating
// authoritative collection "silently skips or repeats rows, which is unacceptable for order
// and ledger reads". An offset is a position in a result set that is not stable while rows
// are being inserted, so this type has no offset field at all rather than one that is
// discouraged. There is nothing to misuse.
type Pagination struct {
	// Limit is the maximum items to return, 1..500.
	Limit int32
	// Cursor is an opaque keyset cursor from a previous response. Opaque means the client
	// must not parse it: its internal structure is not a contract, and a client that
	// depends on it is pinned to an implementation detail.
	Cursor *string
	// Order defaults to descending, so the newest authoritative state is never skipped.
	Order SortOrder
}

// NewPagination builds a page request, treating a limit of 0 as "unset" and taking the
// schema default, then validating the result.
//
// The 0-means-unset convention belongs to this constructor only, not to decoding. The
// schema requires limit with a minimum of 1, so a document carrying an explicit 0 is a
// violation and is rejected. This constructor is the programmatic entry point where "not
// specified" needs a representation, and 0 is the only value outside the schema's range,
// so it is used as that sentinel. Callers needing to be explicit should pass a real limit.
func NewPagination(limit int32, cursor *string, order SortOrder) (Pagination, error) {
	if limit == 0 {
		limit = DefaultPageLimit
	}
	if order == "" {
		order = OrderDescending
	}
	p := Pagination{Limit: limit, Cursor: cursor, Order: order}
	if err := p.Validate(); err != nil {
		return Pagination{}, err
	}
	return p, nil
}

// Validate checks the page request against pagination.schema.json.
func (p Pagination) Validate() error {
	// limit == 0 is not defaulted here. Defaulting is NewPagination's job, because a
	// decoded document that explicitly carried limit 0 is a schema violation and must be
	// rejected, whereas an absent limit is a defaultable case. Collapsing the two would let
	// an explicit 0 through as if it had been omitted.
	if p.Limit < MinPageLimit || p.Limit > MaxPageLimit {
		return fmt.Errorf(
			"%w: limit %d is outside %d..%d", ErrInvalidPagination, p.Limit, MinPageLimit, MaxPageLimit,
		)
	}
	if p.Cursor != nil && len(*p.Cursor) > MaxCursorLength {
		return fmt.Errorf(
			"%w: cursor is %d characters, exceeding the %d-character limit",
			ErrInvalidPagination, len(*p.Cursor), MaxCursorLength,
		)
	}
	if !p.Order.Valid() {
		return fmt.Errorf(
			"%w: order %q is not a known sort order; unknown values are unsupported, not mapped to a default",
			ErrInvalidPagination, p.Order,
		)
	}
	return nil
}

// paginationWire mirrors pagination.schema.json exactly.
//
// Limit is a pointer so an absent limit stays distinguishable from an explicit 0. The
// schema requires limit and gives it a minimum of 1, so an explicit 0 is a violation that
// must be rejected. Collapsing the two would silently accept a document the schema
// rejects, which is precisely the pagination/reject-limit-zero corpus case.
type paginationWire struct {
	Limit  *int32    `json:"limit"`
	Cursor *string   `json:"cursor,omitempty"`
	Order  SortOrder `json:"order,omitempty"`
}

// MarshalJSON encodes a page request, omitting the optional fields when unset.
func (p Pagination) MarshalJSON() ([]byte, error) {
	if err := p.Validate(); err != nil {
		return nil, err
	}
	limit := p.Limit
	return json.Marshal(paginationWire{Limit: &limit, Cursor: p.Cursor, Order: p.Order})
}

// UnmarshalJSON decodes a page request, applying the schema default for an absent limit and
// order before validating.
//
// An explicit limit, including 0, is passed through to Validate unchanged. Only an absent
// limit takes the default, because the schema's default applies to an omitted property, not
// to a supplied one.
func (p *Pagination) UnmarshalJSON(data []byte) error {
	var wire paginationWire
	if err := decodeStrict(data, &wire); err != nil {
		return err
	}
	limit := DefaultPageLimit
	if wire.Limit != nil {
		limit = *wire.Limit
	}
	order := wire.Order
	if order == "" {
		order = OrderDescending
	}
	decoded := Pagination{Limit: limit, Cursor: wire.Cursor, Order: order}
	if err := decoded.Validate(); err != nil {
		return err
	}
	*p = decoded
	return nil
}
