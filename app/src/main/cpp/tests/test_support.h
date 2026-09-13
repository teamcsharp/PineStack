/* tests/test_support.h - a test runner small enough to read in one sitting.
 *
 * No framework, on purpose: this tree has to configure and build on a bare
 * machine with a compiler and CMake and nothing else, and pulling GoogleTest
 * over the network to check that a trim window mirrors correctly would be a
 * poor trade.
 *
 * Each test file defines PB_TEST_MAIN before including this, writes its cases
 * with PB_TEST, and CMake registers the executable with CTest.
 */
#ifndef PINEBOX_TEST_SUPPORT_H
#define PINEBOX_TEST_SUPPORT_H

#include <cmath>
#include <cstdio>
#include <cstring>
#include <map>
#include <string>
#include <vector>

namespace pbtest {

struct Case {
  const char* name;
  void (*run)();
};

inline std::vector<Case>& registry() {
  static std::vector<Case> cases;
  return cases;
}

inline int& failures() {
  static int count = 0;
  return count;
}

/* Levels::perPad, read without writing to it.
 *
 * `levels.perPad["kick"]` does not compile against the `const Levels` these
 * tests hold, and making the Levels non-const to get around that would be
 * worse than the error: std::map::operator[] INSERTS a zero for a key that
 * is not there, so a probe for a pad that should be silent would quietly
 * create it and the very next perPad.size() assertion would be checking a
 * map the test itself had grown. A lookup is a lookup. */
inline int padCount(const std::map<std::string, int>& perPad,
                    const std::string& padId) {
  const auto found = perPad.find(padId);
  return found == perPad.end() ? 0 : found->second;
}

inline const char*& current() {
  static const char* name = "";
  return name;
}

struct Registrar {
  Registrar(const char* name, void (*run)()) { registry().push_back({name, run}); }
};

inline void fail(const char* file, int line, const std::string& message) {
  failures() += 1;
  std::fprintf(stderr, "  FAIL %s\n    %s:%d\n    %s\n", current(), file, line,
               message.c_str());
}

inline void check(bool ok, const char* file, int line, const char* expression,
                  const std::string& note) {
  if (ok) return;
  fail(file, line,
       std::string(expression) + (note.empty() ? "" : "  -- " + note));
}

inline void checkNear(double got, double want, double tolerance,
                      const char* file, int line, const char* expression,
                      const std::string& note) {
  if (std::fabs(got - want) <= tolerance) return;
  char buffer[256];
  std::snprintf(buffer, sizeof(buffer), "%s: got %.9g, wanted %.9g (+/- %.9g)",
                expression, got, want, tolerance);
  fail(file, line, std::string(buffer) + (note.empty() ? "" : "  -- " + note));
}

}  // namespace pbtest

#define PB_TEST(name)                                                    \
  static void pb_case_##name();                                          \
  static ::pbtest::Registrar pb_reg_##name(#name, &pb_case_##name);      \
  static void pb_case_##name()

#define PB_CHECK(expr) \
  ::pbtest::check((expr), __FILE__, __LINE__, #expr, "")
#define PB_CHECK_MSG(expr, note) \
  ::pbtest::check((expr), __FILE__, __LINE__, #expr, (note))
#define PB_NEAR(got, want, tol) \
  ::pbtest::checkNear((got), (want), (tol), __FILE__, __LINE__, #got, "")
#define PB_NEAR_MSG(got, want, tol, note) \
  ::pbtest::checkNear((got), (want), (tol), __FILE__, __LINE__, #got, (note))
#define PB_EQ(got, want) \
  ::pbtest::check((got) == (want), __FILE__, __LINE__, #got " == " #want, "")
#define PB_EQ_MSG(got, want, note) \
  ::pbtest::check((got) == (want), __FILE__, __LINE__, #got " == " #want, (note))

#ifdef PB_TEST_MAIN
int main(int argc, char** argv) {
  const char* only = nullptr;
  for (int i = 1; i < argc; ++i) {
    if (std::strcmp(argv[i], "--case") == 0 && i + 1 < argc) only = argv[++i];
    if (std::strcmp(argv[i], "--list") == 0) {
      for (const auto& entry : ::pbtest::registry()) {
        std::printf("%s\n", entry.name);
      }
      return 0;
    }
  }
  int ran = 0;
  for (const auto& entry : ::pbtest::registry()) {
    if (only && std::strcmp(only, entry.name) != 0) continue;
    ::pbtest::current() = entry.name;
    const int before = ::pbtest::failures();
    entry.run();
    ran += 1;
    std::printf("%s %s\n",
                ::pbtest::failures() == before ? "  ok  " : "  BAD ", entry.name);
  }
  std::printf("%d case(s), %d failure(s)\n", ran, ::pbtest::failures());
  return ::pbtest::failures() == 0 ? 0 : 1;
}
#endif

#endif  /* PINEBOX_TEST_SUPPORT_H */
