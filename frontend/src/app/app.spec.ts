import { provideHttpClient } from '@angular/common/http';
import { TestBed } from '@angular/core/testing';
import { Router, provideRouter } from '@angular/router';

import { App } from './app';
import { provideTranslations } from './core/i18n/translation.config';

describe('App', () => {
  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [App],
      providers: [provideRouter([]), provideHttpClient(), provideTranslations()],
    }).compileComponents();
  });

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
