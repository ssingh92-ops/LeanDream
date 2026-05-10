namespace LeanDream

inductive Circuit
  | var   : Nat → Circuit
  | const : Bool → Circuit
  | not   : Circuit → Circuit
  | and   : Circuit → Circuit → Circuit
  | or    : Circuit → Circuit → Circuit
  | xor   : Circuit → Circuit → Circuit
  deriving Repr, BEq, DecidableEq

def Circuit.eval : Circuit → (Nat → Bool) → Bool
  | .var i,    env => env i
  | .const b,  _   => b
  | .not c,    env => !(c.eval env)
  | .and a b,  env => (a.eval env) && (b.eval env)
  | .or  a b,  env => (a.eval env) || (b.eval env)
  | .xor a b,  env => Bool.xor (a.eval env) (b.eval env)

/-- Build a `Nat → Bool` lookup environment from a finite list. -/
def envOf (xs : List Bool) : Nat → Bool :=
  fun i => xs[i]?.getD false

/-- All `List Bool` of length `n`, in lex order. -/
def allEnvs : Nat → List (List Bool)
  | 0     => [[]]
  | n + 1 =>
    let prev := allEnvs n
    prev.map (fun xs => false :: xs) ++ prev.map (fun xs => true :: xs)

/-- Two circuits are equivalent on `arity`-many inputs iff they agree
    on every Boolean assignment to those inputs. Returns `Bool` so the
    check can be discharged by `native_decide`. -/
def Circuit.equivOn (arity : Nat) (c ref : Circuit) : Bool :=
  (allEnvs arity).all (fun xs => c.eval (envOf xs) == ref.eval (envOf xs))

end LeanDream
