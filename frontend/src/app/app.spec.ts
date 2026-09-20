import { provideHttpClient } from '@angular/common/http';
import { TestBed } from '@angular/core/testing';
import { Router, provideRouter } from '@angular/router';

import { App } from './app';
import { TokenStorage } from './core/auth/token-storage';
import { provideTranslations } from './core/i18n/translation.config';

describe('App', () => {
  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [App],
      providers: [
        provideRouter([
          { path: 'projects', children: [] },
          { path: 'auth/login', children: [] },
        ]),
        provideHttpClient(),
        provideTranslations(),
      ],
    }).compileComponents();
  });

  afterEach(() => localStorage.clear());

  it('creates the shell', () => {
    const fixture = TestBed.createComponent(App);

    expect(fixture.componentInstance).toBeTruthy();
  });

  it('renders the product name through the translation pipe', async () => {
    const fixture = TestBed.createComponent(App);
    await fixture.whenStable();

    const mark = (fixture.nativeElement as HTMLElement).querySelector('.app-header__mark');

    // No translation file is loaded in the test, so ngx-translate falls back to
    // echoing the key. Asserting the key rather than the English text keeps this
    // test from breaking every time the wording changes — and it still proves
    // the string goes through the pipe instead of being hard-coded.
    expect(mark?.textContent?.trim()).toBe('app.title');
  });

  it('draws the casing zone when a route asks for nothing', async () => {
    const fixture = TestBed.createComponent(App);
    await fixture.whenStable();

    const shell = (fixture.nativeElement as HTMLElement).querySelector('.app-shell');

    // Casing is the default precisely so that only the editor has to declare a
    // zone; a route that says nothing must never land somewhere unstyled.
    expect(shell?.classList.contains('zone-casing')).toBe(true);
  });

  it('offers no menu while there is nowhere to go', async () => {
    // Signed out, the casing holds only the two forms, and each already links
    // to the other. A menu there would offer the screen being looked at.
    const fixture = TestBed.createComponent(App);
    await fixture.whenStable();

    const element = fixture.nativeElement as HTMLElement;

    expect(element.querySelector('.app-header__nav')).toBeNull();
    expect(element.querySelector('a.app-header__mark')).toBeNull();
  });

  it('signed in, every screen in the casing carries the way out', async () => {
    // The header is the one thing every casing screen shares, so it is where
    // leaving has to live: nothing else on the upload screen goes anywhere.
    TestBed.inject(TokenStorage).set('a.b.c');

    const fixture = TestBed.createComponent(App);
    await fixture.whenStable();

    const element = fixture.nativeElement as HTMLElement;
    const links = element.querySelectorAll('.app-header__link');

    expect(element.querySelector('a.app-header__mark')?.getAttribute('href')).toBe('/projects');
    expect(links).toHaveLength(2);
    expect(links[0].getAttribute('href')).toBe('/projects');
  });

  it('signing out drops the token and goes back to the form', async () => {
    const tokens = TestBed.inject(TokenStorage);
    tokens.set('a.b.c');

    const fixture = TestBed.createComponent(App);
    await fixture.whenStable();

    const signOut = [...(fixture.nativeElement as HTMLElement).querySelectorAll('button')].at(-1);
    signOut!.click();
    await fixture.whenStable();

    expect(tokens.isAuthenticated()).toBe(false);
    expect(TestBed.inject(Router).url).toBe('/auth/login');
  });

  it('draws the display zone, without the header, for a route that asks for it', async () => {
    // The header is chrome around a page. The editor draws its own full-bleed
    // surface, so the shell steps out of the way rather than framing it.
    TestBed.resetTestingModule();
    await TestBed.configureTestingModule({
      imports: [App],
      providers: [
        provideRouter([{ path: '', children: [], data: { zone: 'display' } }]),
        provideHttpClient(),
        provideTranslations(),
      ],
    }).compileComponents();

    const harness = TestBed.inject(Router);
    await harness.navigate(['/']);

    const fixture = TestBed.createComponent(App);
    await harness.navigate(['/']);
    await fixture.whenStable();
    fixture.detectChanges();

    const element = fixture.nativeElement as HTMLElement;

    expect(element.querySelector('.app-shell')?.classList.contains('zone-display')).toBe(true);
    expect(element.querySelector('.app-header')).toBeNull();
  });
});
