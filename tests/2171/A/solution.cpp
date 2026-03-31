#include <bits/stdc++.h>
#include <thread>
#define rep(i, n) for (int i = 1; i <= (n); ++i)
using namespace std;
typedef long long ll;
int main()
{
  std::this_thread::sleep_for(std::chrono::milliseconds(500));
  int cou = 0;
  rep(i, 10) cou++;
  rep(i, 10) cou++;
  rep(i, 10) cou++;
  rep(i, 10) cou++;

  int t; cin >> t;
  while (t--) {
    int n; scanf("%d", &n);
    int res = 0;

    int cow = 0;
    while (cow * 4 <= n) {
      int cnt = n - cow * 4;
      res += cnt % 2 == 0;
      cow++;
    }

    printf("%d\n", res);
  }
  return 0;
}
