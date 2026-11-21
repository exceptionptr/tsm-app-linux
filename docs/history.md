# TSM Linux Support A Complete History

_Personal record compiled March 2026, updated November 2026 (project archived)_

---

## Background

TradeSkillMaster (TSM) is a World of Warcraft addon and desktop application used extensively by the gold-making community. The desktop app acts as a bridge between the TSM website and the in-game addon, handling data sync, price updates, and more. It has historically been Windows/Mac only.

The core addon and desktop app are free. TSM also offers a paid premium tier which provides additional API-powered features such as hot deal alerts and extended data on the website. The premium tier is optional and does not gate core functionality.

This document records the full history of community attempts to get Linux support, TSM's responses, and the personal experience that led to compiling this record.

---

## The Public Repository

TSM published their desktop application source code on Bitbucket under the GPLv3 license:

**Repository:** `https://bitbucket.org/tradeskillmaster/tsmapplication_public`

The application was written in Python 3.4.3 with PyQt 5.5.1. The last commit to this repository was in **2016**, after which TSM moved to a closed-source model.

### The License Problem

The repository's LICENSE.md states:

> _"This application uses TradeSkillMaster App APIs. You are permitted to use the TSM App APIs through an unmodified, officially-released version of this application. You are also permitted to use the TSM App APIs in a modified version of this works for the purpose of contributing modifications back to the official repository..."_
> _"Any other usage of the TSM App APIs is strictly forbidden."_

This is legally questionable, and the structure of how it is presented makes it more so, not less. Rather than modifying the GPLv3 text itself (which is not permitted), TSM chose to ship a separate LICENSE file alongside the standard GPLv3, using it to layer additional restrictions on top. This is a known anti-pattern. GPLv3 Section 10 explicitly forbids downstream recipients from imposing further restrictions on the rights the license grants. Providing a supplementary file that says "you may only use our API through our official unmodified client" does not circumvent that prohibition - it is exactly the kind of further restriction the GPL was designed to prevent. If anything, the deliberate separation into a second file suggests awareness that the restriction was problematic, since it could not simply be written into the GPL text itself.

German courts, which have a strong track record of actually enforcing the GPL, would likely look at this construction very skeptically.

The API itself is not "private" in any technical sense: it is accessed with standard user credentials, and the HMAC secret used for authentication is hardcoded in the publicly released client.

---

## Timeline of Events

### January–February 2016 The First Linux PR

A community member submitted **Pull Request #1** to the public Bitbucket repository titled _"Initial Linux Build Support."_

**What the PR included:**

- Changes to enable native operation on Linux (WoW installed through Wine)
- Builder updates to ignore autostartup on Linux
- Hard-coded WoW path workaround
- Disabled auto-startup feature
- Renamed addon paths for Linux filesystem compatibility

**February 13, 2016 Sapu declines the PR**, commenting:

> _"Sorry, I didn't get any email when this was first posted so just saw it. If this the app is working in wine now then I don't see any reason to have a native version either."_

The PR submitter and another user (Asa Ayers) noted that the app had started working in Wine (r303), which TSM used as justification to decline the PR. Asa Ayers had been actively reviewing the code and asking constructive questions about what was needed to get it merged.

**Key observation:** The PR was declined not because the code was bad, but because a Wine workaround existed. This set the precedent that would be repeated for the next decade.

---

### July 2017 "We Do Not Support Linux"

A user named **seirl** asked in the TSM Discord whether the Linux build was broken for the desktop app, noting a code assertion: `assert(IS_WINDOWS != IS_MAC) # only one should be set`

**TSM team member Bart39 responded:**

> _"We do not support linux"_
> _"via wine is your only option"_

seirl pushed back, noting they wanted to run it natively as a Python script without Wine, and pointed out the public GPLv3 repository. Bart39 acknowledged the repo but doubted TSM would give "seal of approval" to a community fork, suggesting seirl email <admin@tradeskillmaster.com>.

---

### June 2018 seirl Returns, Calls It Out Directly

seirl returned to the TSM Discord, asking whether the public Bitbucket repo could be updated to fix Linux compatibility issues (Wine was crashing their virtual framebuffer setup).

**Sapu responded:** _"That's not something we support"_

seirl said they were happy to fix it themselves if they had the resources. Sapu directed them to "refer to the license in that repo" using the restrictive API clause as a shield.

seirl then linked the declined 2016 PR and made the observation that has aged well:

> _"seems contradictory, except the message is just 'we don't care about linux users'"_

Sapu's response to the declined PR: it was rejected because the author got it working in Wine, so there was "no reason to merge it."

seirl asked directly: _"well, if i'm not, would you accept a first party solution?"_

Sapu said they could open a PR, but noted the public repo "will be updated eventually." seirl pointed out that updating the repo would be a prerequisite for any PR to be mergeable against the new codebase.

**The repo was never updated.**

seirl subsequently published their own fork on GitHub (`github.com/seirl/tsmapplication_public`), which has had no commits since approximately 9 years ago. No action was ever taken by TSM against this public repository.

---

### September 2024 The "Legacy App" Signal

A user named seirl noticed that TSM download links pointed to a URL containing `legacyDesktopApp/setup.exe` and asked whether a new app was in development.

**Sapu's response (September 8, 2024):**

> _"there's nothing to announce about any new app right now - if you want to try to speculate based on a random URL you're free to do so"_

This is notable: as of at least September 2024, there was internal infrastructure suggesting a new app, but no public acknowledgment.

---

### March 2026 My Experience

I built a native Linux client for TSM and published it on Reddit (r/woweconomy) and the Arch AUR. The Reddit post was not unlocked by moderators. I received a private Discord DM from Sapu from the woweconomy Discord server.

**The conversation (March 18, 2026):**

> **Sapu:** Hey, I saw the Linux app you posted. That's cool to see that you made that, but for various reasons, I would ask that you not distribute an application which uses our private API.

> **Me:** Hi, my intention was to build a Linux-native client for personal and community use, not to cause problems for TSM. Just to be sure: You want me to make the repository private and remove the Arch AUR?

> **Sapu:** Yeah, please do

> **Me:** Done

> **Sapu:** Thanks

> **Me:** Thanks for not banning me and reaching out 😂

> **Sapu:** Easier to just reach out 🙂 We have a new app in the works which should support Linux better anyways

The conversation was friendly and professional. No threats were made. I complied in good faith.

**Key observations from this interaction:**

- The "new app" has been signaled since at least September 2024 (the legacy URL) 18+ months before this conversation with still no public timeline
- TSM's community channels (r/woweconomy, woweconomy Discord) give them significant control over the narrative around competing tools
- The "private API" framing is difficult to reconcile with 9 years of a public GPLv3 repository containing the full API implementation

---

### April 7, 2026 The app goes live again

After the conversation in March I looked closely at how the TSM team had dealt with the community and with Linux support over the years (see the timeline above and the sections below). That made me decide to put the app back online: on April 7, 2026 I made the repository public again.

---

### April 9, 2026 Sapu asks again

Sapu in a Discord message: _"Did you make this public again?"_

---

### November 2026 The new official app, the sync outage, the second takedown request

**New official app.** TSM released the new desktop app (Electron AppImage, version 1.0.11 at the time of analysis) with Linux support. The backend moved from the old HMAC API (`app-server.tradeskillmaster.com/v2`) to Keycloak OIDC (PKCE login), REST services behind Cloudflare and a Socket.IO push channel. This app followed the new protocol (see `docs/api.md` in the repository) and shipped it as 2.0.x.

**Sync outage (around November 9-14).** Auction data stopped arriving. Findings:

- The server pushes only `addon` and `app_info` to the account. Neither this app nor the official AppImage receives `realm_auctiondb`, `realm_shopping` or `region_auctiondb`.
- The official client behaves the same on the same account, so this app is not the cause. AppData timestamps are identical.
- Other users of the official app report the same on their old accounts, and say a new account works.
- Conclusion: a server-side problem bound to specific accounts. Whether it has anything to do with third-party clients is unknown. No evidence for it was found.

**Traffic analysis.** The official client was captured with mitmproxy (headers, methods, paths, bodies). The result is in the repository as `docs/network.md`. In short: REST user agents are `node-fetch` and `node`, the socket uses `node-XMLHttpRequest` long polling before the websocket upgrade, and two calls this app does not make exist (`/group-sends/claim`, `/local-machine-name`). Until 2.0.x this app identified itself as `tsm-app-linux/<version>` and connected over a plain websocket. No hardware ids or file lists were seen leaving the machine in the captured session.

**November 13, 2026 Sapu's second message** (Discord screenshot, "Yesterday at 4:59 PM" on the 14th):

> _"Hello, I'd like to ask you again to take this down. We've released an official TSM app that supports Linux now that people should be using. 3rd party tools accessing our non-public APIs is against our ToS."_

**Account bans (around November 15-17, 2026).** Accounts of users of this app were disabled; the author's own account was among them. The Keycloak login shows "Account is disabled, contact your administrator." A repository comment from the owner warned users to stop the app and check their account, and recommended the official AppImage. Users report that TSM also removes mentions of this app on its Discord and in the WoWEconomy subreddit; this is the users' account and was not checked by the author.

**Official app 1.0.13 and 1.0.14 (around November 16, 2026).** TSMBot announced two releases of the official desktop app on TSM's Discord. The only listed change in 1.0.13 is "Behind-the-scenes improvements to the app's connection to TSM's servers", and 1.0.14 says "More behind-the-scenes improvements to the app's connection to TSM's servers". Nothing more specific is published. The author's reading is that this is TSM officially starting to flag users of third-party clients, which fits the account bans above, but the release notes do not say so and the mechanism is unknown. This app's traffic differs from the official client in the ways listed in `docs/network.md`, so treat it as detectable.

**Network alignment with official 1.0.14 (November 17, 2026, development branch only, no release).** The official AppImage 1.0.14 was analysed again, statically and with mitmproxy captures of its Chromium and Node processes, and its socket with the client's own debug log. The development branch now sends what the official client sends instead of its own name and version: the official version 1.0.14 and the user agent of each channel (Chromium for the Keycloak token calls, `node-fetch` for the REST services, `node` for downloads and token revoke, `node-XMLHttpRequest` for the socket), the authorize, token, refresh and revoke request shapes of the Keycloak login, and the socket handshake (long polling first, then the websocket upgrade). Differences that cannot be removed without new dependencies are header order, the TLS fingerprint and the browser client hints, plus the loopback port of the login callback (the official client uses `http://localhost/auth/callback` without a port). The details are in `docs/network.md` and `docs/api.md`. This makes the requests look like the official client's, it does not make the app official, and it does not remove the risk described above: TSM can still tell the clients apart by other means and has said that third-party clients are against its terms.

**November 17, 2026 TSM contacts users of this app by e-mail.** Users of this app reported on the repository that they received an e-mail from the TradeSkillMaster team within a few hours of each other (quoted by the users, not seen by the author). The text, as quoted:

> _"We noticed you're using an unofficial, third-party app to sync your TSM data. It isn't made by us, so we can't support it, and it may break without warning. Our official TSM Desktop App works on Linux too. It finds WoW installed through Wine, Lutris, Bottles or Steam automatically, and you sign in with your usual TSM account. Get it at tradeskillmaster.com/download. If you need a hand getting set up, come find us on Discord."_

This confirms that TSM can identify which accounts use a third-party client. How it does so is unknown.

**Official app and stale data (reported November 17, 2026).** One of the users who got the e-mail replied that the official app does not provide updated data either, even though it says "up to date", which matches the sync outage described above. The same user asked when the community will build its own database and data sharing. No such project exists yet and this app does not provide one; it only writes the data TSM's servers push to the user's own account. The question is recorded here as a request from the community, not as a plan.

---

### November 21, 2026 The project is archived

I am archiving the repository. I no longer want to see dozens of users' accounts banned every day, only to keep fighting TSM's countermeasures. TSM's team spends its time working against a tiny app that hardly anyone uses, and opinions, bug reports and patches about it are suppressed in the community spaces TSM controls. This is not worth the cost to the users. No further releases, fixes or patches will follow. Anyone who needs TSM on Linux should use the official app.

---

## Legal Analysis (Germany)

For anyone in Germany considering a similar project, the legal position is strong:

**ToS violations are not criminal.** In Germany, Terms of Service violations are grounds for account termination, not lawsuits.

**Reverse engineering for interoperability is protected** under EU Directive 2009/24/EC (Software Directive, Article 6) when necessary for compatibility. In this case, reverse engineering wasn't even required the API was documented in a public repository.

**Using your own credentials is not hacking.** §202a StGB (the German computer fraud equivalent) requires circumventing access protection. Logging in normally with your own username and password does not qualify.

**The GPLv3 API restriction is legally shaky.** The additional restriction "you may only use our API through our official unmodified client" sitting on top of GPLv3 code is likely unenforceable. GPLv3 Section 10 forbids adding further restrictions on the rights the license grants. German courts take GPL enforcement seriously and have ruled on it multiple times.

**Realistic worst case:** Account bans for users of a community app, and removal from TSM-controlled channels (r/woweconomy, woweconomy Discord). A cease and desist letter is possible but would have little teeth in Germany for the reasons above.

---

## The Broader Pattern

The record across a decade is consistent:

1. Linux user encounters the problem
2. Finds the public repo or tries to contribute
3. Gets told Wine is the only option, and pointed to a community channel for help
4. Gets pointed to a restrictive license if they push further
5. TSM vaguely suggests future support is coming
6. Nothing changes

To be fair, TSM does not simply tell Linux users to get lost. They are typically redirected to a specific Discord channel where community members share Wine-based workarounds, and some users do get things working that way. The position is "not officially supported, but here is where others have solved it." That is partial helpfulness, and it is worth acknowledging. What it is not is a path to native support, and it has not changed in a decade.

The transition to a closed-source model in 2016 right after the Linux PR was declined and the community began asking questions about the GPLv3 license is worth noting. Whether the public scrutiny was a factor in that decision is speculation, but the timing fits.

seirl's 2018 summary remains accurate: _"the message is just 'we don't care about linux users.'"_

---

## The Gumdrops Conflict of Interest

A structural issue worth documenting separately: the two largest community hubs for WoW gold-making, r/woweconomy (166k members) and the woweconomy Discord (70k+ members), are not neutral community spaces. Both are controlled by a single person, Gumdrops, who is simultaneously the TSM Support Manager and a paid member of the TSM team.

Gumdrops did not join TSM and then get handed these platforms. He built them first, then joined TSM officially after already controlling the community infrastructure. From his own account, he "took over" r/woweconomy and later founded the Discord server, which then became the official TSM support channel. The community followed the platform; the platform was then absorbed into the team.

The practical consequence is concrete. When the Linux client was posted, two things happened in quick succession: the Reddit post was suppressed without explanation, and a message posted in the woweconomy Discord's off-topic channel was deleted by Gumdrops personally. He informed me directly that he had deleted the message and that a follow-up would come. That follow-up was the private DM from Sapu asking me to take the project down.

This is not a neutral moderation decision by an independent community. It was a TSM team member actively coordinating the suppression of information about a competing tool, and then flagging it internally so that the founder could follow up. The Reddit suppression and the Discord deletion were not independent moderation calls - they were part of a coordinated response, executed through platforms that present themselves as open community spaces.

This is not a conspiracy. It is a quiet, structural conflict of interest that has been baked in since 2016 and is rarely acknowledged. The community largely does not know that the moderator of their supposedly independent subreddit is a salaried member of the team behind the dominant tool being discussed there. Most participants assume they are engaging in open community discussion. In practice, the Overton window of what gets amplified and what gets suppressed is shaped by someone with a direct financial interest in TSM's continued dominance.

This matters for the Linux situation specifically. It is not just that TSM declined to support Linux users for a decade. It is that the community spaces where Linux users might have organized, shared workarounds, or elevated the issue were administered by someone whose job was TSM community management. Whether posts about Linux alternatives were suppressed deliberately or simply deprioritized as off-topic, the effect is the same: the issue stayed quiet.

We view this critically. A community platform at this scale, used as the primary support and discussion venue for a paid commercial product, should be transparent about who runs it and in what capacity. It currently is not.

---

## Notes on TSM as a Project

TSM is a genuinely impressive piece of software maintained by a small team, some of whom work on it full time. The core product is free, which reflects a genuine commitment to accessibility for the gold-making community. The premium tier exists to fund development and offers real additional value rather than paywalling core features. The gold-making community has benefited enormously from what they've built. Sapu in particular has been consistently decent in personal interactions even when the answer was no.

The frustration documented here is not with the people, and it is not with the product itself. It is with a decade-long pattern of a small team using their community platform control to suppress tools that fill a gap they acknowledge but have not prioritized, while pointing Linux users toward workarounds rather than solutions. Those things are separable from the quality of the software and the intentions of the team.

---

_Last updated: November 21, 2026_
