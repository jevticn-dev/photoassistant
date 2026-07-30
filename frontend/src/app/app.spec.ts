import { provideHttpClient } from '@angular/common/http';
import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';

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

  it('renders the heading through the translation pipe', async () => {
    const fixture = TestBed.createComponent(App);
    await fixture.whenStable();

    const heading = (fixture.nativeElement as HTMLElement).querySelector('h1');

    // No translation file is loaded in the test, so ngx-translate falls back to
    // echoing the key. Asserting the key rather than the English text keeps this
    // test from breaking every time the wording changes — and it still proves
    // the string goes through the pipe instead of being hard-coded.
    expect(heading?.textContent?.trim()).toBe('app.title');
  });
});
