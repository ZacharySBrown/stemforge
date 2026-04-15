// test_framework.hpp — ~40 LOC test runner. Sufficient for v0 unit tests.

#pragma once
#include <cstdio>
#include <functional>
#include <string>
#include <vector>

struct TestCase {
    std::string name;
    std::function<void()> fn;
};

inline std::vector<TestCase> &registry() {
    static std::vector<TestCase> r; return r;
}

struct TestRegistrar {
    TestRegistrar(const std::string &name, std::function<void()> fn) {
        registry().push_back({name, std::move(fn)});
    }
};

#define TEST(NAME)                                                    \
    static void NAME();                                               \
    static TestRegistrar _reg_##NAME(#NAME, NAME);                    \
    static void NAME()

#define CHECK(cond) do {                                              \
    if (!(cond)) {                                                    \
        std::fprintf(stderr, "  FAIL %s:%d  %s\n", __FILE__, __LINE__, #cond); \
        throw std::runtime_error("assertion failed");                 \
    } } while (0)

#define CHECK_EQ(a, b) do {                                           \
    auto _a = (a); auto _b = (b);                                     \
    if (!(_a == _b)) {                                                \
        std::fprintf(stderr, "  FAIL %s:%d  %s == %s\n", __FILE__, __LINE__, #a, #b); \
        throw std::runtime_error("assertion failed");                 \
    } } while (0)

inline int run_all_tests() {
    int pass = 0, fail = 0;
    for (auto &t : registry()) {
        std::fprintf(stderr, "[RUN ] %s\n", t.name.c_str());
        try { t.fn(); std::fprintf(stderr, "[PASS] %s\n", t.name.c_str()); ++pass; }
        catch (const std::exception &e) {
            std::fprintf(stderr, "[FAIL] %s: %s\n", t.name.c_str(), e.what());
            ++fail;
        } catch (...) {
            std::fprintf(stderr, "[FAIL] %s: unknown\n", t.name.c_str());
            ++fail;
        }
    }
    std::fprintf(stderr, "%d passed, %d failed\n", pass, fail);
    return fail == 0 ? 0 : 1;
}
