package ui

import (
	"testing"
	"time"
)

func TestDefaultIntervals(t *testing.T) {
	iv := DefaultIntervals()
	if iv.Fast != time.Minute {
		t.Errorf("fast = %v; want 1m", iv.Fast)
	}
	if iv.Slow != 4*time.Minute {
		t.Errorf("slow = %v; want 4m", iv.Slow)
	}
	if iv.Slow != iv.Fast*slowIntervalFactor {
		t.Errorf("slow (%v) != fast*%d (%v)", iv.Slow, slowIntervalFactor, iv.Fast*slowIntervalFactor)
	}
}

func TestFastTickProducesFastTickMsg(t *testing.T) {
	// Use a 1ns interval so the underlying timer Cmd returns promptly; we assert
	// only the message type, not timing.
	cmd := fastTick(time.Nanosecond)
	if cmd == nil {
		t.Fatal("fastTick returned nil Cmd")
	}
	msg := cmd()
	if _, ok := msg.(fastTickMsg); !ok {
		t.Fatalf("msg type = %T; want fastTickMsg", msg)
	}
}

func TestSlowTickProducesSlowTickMsg(t *testing.T) {
	cmd := slowTick(time.Nanosecond)
	if cmd == nil {
		t.Fatal("slowTick returned nil Cmd")
	}
	msg := cmd()
	if _, ok := msg.(slowTickMsg); !ok {
		t.Fatalf("msg type = %T; want slowTickMsg", msg)
	}
}

// The real I2 re-arm invariant (a fastTickMsg / slowTickMsg handler re-arms
// exactly its own tier and dispatches the right fetch) is asserted against the
// root model in app_test.go, which replaces the Phase-2 placeholder that lived
// here.
