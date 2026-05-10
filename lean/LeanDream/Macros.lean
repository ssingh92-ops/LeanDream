import LeanDream.DSL

namespace LeanDream.Macros
open LeanDream

-- Mined macros are appended below this line by the installer.
-- BEGIN MACROS
def macro_1 (x0 x1 : Circuit) : Circuit := (.and x0 x1)
def macro_2 (x0 x1 : Circuit) : Circuit := (.xor x0 x1)
def macro_3 (x0 x1 x2 : Circuit) : Circuit := (.and x0 (.xor x1 x2))
def macro_4 (x0 x1 x2 : Circuit) : Circuit := (.or (.and x0 x1) (.and x2 (.xor x0 x1)))
def macro_5 (x0 x1 x2 x3 : Circuit) : Circuit := (.xor (.xor x0 x1) (.xor x2 x3))
def macro_6 (x0 x1 x2 : Circuit) : Circuit := (.xor (.xor x0 x1) x2)
def macro_7 (x0 x1 : Circuit) : Circuit := (.or x0 x1)
def macro_8 (x0 x1 x2 x3 x4 x5 : Circuit) : Circuit := (.and (.and (.not (.xor x0 x1)) (.not (.xor x2 x3))) (.not (.xor x4 x5)))
def macro_9 (x0 x1 x2 x3 : Circuit) : Circuit := (.and (.not (.xor x0 x1)) (.not (.xor x2 x3)))
def macro_10 (x0 x1 x2 : Circuit) : Circuit := (.xor x0 (.and x1 (.xor x2 x0)))
def macro_11 (x0 x1 : Circuit) : Circuit := (.and x0 (.xor x1 (.const true)))
def macro_12 (x0 : Circuit) : Circuit := (.xor x0 (.const true))
def macro_13 (x0 x1 x2 x3 : Circuit) : Circuit := (.and (.and x0 x1) (.and x2 x3))
def macro_14 (x0 x1 x2 : Circuit) : Circuit := (.and (.and x0 x1) x2)
def macro_15 (x0 x1 x2 : Circuit) : Circuit := (.or (.or x0 x1) x2)
def macro_16 (x0 x1 x2 x3 x4 x5 x6 x7 : Circuit) : Circuit := (.xor (.xor (.xor x0 x1) (.xor x2 x3)) (.xor (.xor x4 x5) (.xor x6 x7)))
def macro_17 (x0 x1 x2 x3 x4 x5 : Circuit) : Circuit := (.xor (.xor (.xor x0 x1) (.xor x2 x3)) (.xor x4 x5))
def macro_18 (x0 x1 x2 x3 x4 x5 x6 : Circuit) : Circuit := (.or (.and (.or (.and x0 x1) (.and x2 (.xor x0 x1))) (.or (.and x3 x4) (.and x5 (.xor x3 x4)))) (.and (.or (.and (.xor (.xor x0 x1) x2) (.xor (.xor x3 x4) x5)) (.and x6 (.xor (.xor (.xor x0 x1) x2) (.xor (.xor x3 x4) x5)))) (.xor (.or (.and x0 x1) (.and x2 (.xor x0 x1))) (.or (.and x3 x4) (.and x5 (.xor x3 x4))))))
def macro_19 (x0 x1 x2 x3 x4 x5 x6 : Circuit) : Circuit := (.and (.or (.and (.xor (.xor x0 x1) x2) (.xor (.xor x3 x4) x5)) (.and x6 (.xor (.xor (.xor x0 x1) x2) (.xor (.xor x3 x4) x5)))) (.xor (.or (.and x0 x1) (.and x2 (.xor x0 x1))) (.or (.and x3 x4) (.and x5 (.xor x3 x4)))))
def macro_20 (x0 x1 x2 x3 x4 x5 x6 : Circuit) : Circuit := (.or (.and (.xor (.xor x0 x1) x2) (.xor (.xor x3 x4) x5)) (.and x6 (.xor (.xor (.xor x0 x1) x2) (.xor (.xor x3 x4) x5))))
def macro_21 (x0 x1 x2 x3 x4 x5 : Circuit) : Circuit := (.and (.or (.and x0 x1) (.and x2 (.xor x0 x1))) (.or (.and x3 x4) (.and x5 (.xor x3 x4))))
def macro_22 (x0 x1 x2 x3 x4 x5 : Circuit) : Circuit := (.xor (.or (.and x0 x1) (.and x2 (.xor x0 x1))) (.or (.and x3 x4) (.and x5 (.xor x3 x4))))
def macro_23 (x0 x1 x2 x3 x4 x5 x6 : Circuit) : Circuit := (.and x0 (.xor (.xor (.xor x1 x2) x3) (.xor (.xor x4 x5) x6)))
def macro_24 (x0 x1 x2 x3 x4 x5 : Circuit) : Circuit := (.and (.xor (.xor x0 x1) x2) (.xor (.xor x3 x4) x5))
-- END MACROS

end LeanDream.Macros
