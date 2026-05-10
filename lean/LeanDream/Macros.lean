import LeanDream.DSL

namespace LeanDream.Macros
open LeanDream

-- Mined macros are appended below this line by the installer.
-- BEGIN MACROS
def macro_1 (x0 x1 : Circuit) : Circuit := (.and x0 x1)
def macro_2 (x0 x1 : Circuit) : Circuit := (.xor x0 x1)
def macro_3 (x0 x1 : Circuit) : Circuit := (.or x0 x1)
def macro_4 (x0 x1 x2 : Circuit) : Circuit := (.or (.and x0 x1) (.and x2 (.xor x0 x1)))
def macro_5 (x0 x1 x2 : Circuit) : Circuit := (.or (.and x0 x1) (.and (.not x0) x2))
def macro_6 (x0 x1 x2 : Circuit) : Circuit := (.and x0 (.xor x1 x2))
def macro_7 (x0 x1 : Circuit) : Circuit := (.and (.not x0) x1)
def macro_8 (x0 x1 x2 : Circuit) : Circuit := (.xor x0 (.xor x1 x2))
def macro_9 (x0 x1 x2 x3 : Circuit) : Circuit := (.xor x0 (.xor x1 (.xor x2 (.xor x3 (.const false)))))
def macro_10 (x0 : Circuit) : Circuit := (.xor x0 (.const false))
def macro_11 (x0 x1 x2 : Circuit) : Circuit := (.or (.and x0 x1) (.and x1 x2))
-- END MACROS

end LeanDream.Macros
