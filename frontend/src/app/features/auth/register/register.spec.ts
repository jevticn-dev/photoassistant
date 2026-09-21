import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { Router, provideRouter } from '@angular/router';

import { environment } from '../../../../environments/environment';
import { TokenStorage } from '../../../core/auth/token-storage';
import { provideTranslations } from '../../../core/i18n/translation.config';
import { Register } from './register';

const SESSION = {
  accessToken: 'a.b.c',
  expiresAt: '2026-09-19T00:00:00+00:00',
  userId: '00000000-0000-0000-0000-000000000001',
  email: 'nikola@test.rs',
};

const ENDPOINT = `${environment.apiBaseUrl}/auth/register`;

describe('Register', () => {
  let fixture: ComponentFixture<Register>;
  let http: HttpTestingController;

  beforeEach(async () => {
    localStorage.clear();
    await TestBed.configureTestingModule({
      imports: [Register],
      providers: [
        provideRouter([{ path: 'projects', children: [] }]),
        provideHttpClient(),
        provideHttpClientTesting(),
        provideTranslations(),
      ],
    }).compileComponents();

    fixture = TestBed.createComponent(Register);
    http = TestBed.inject(HttpTestingController);
    fixture.detectChanges();
  });

  afterEach(() => {
    http.match((request) => request.url.includes('/i18n/')).forEach((request) => request.flush({}));
    http.verify();
  });

  function element(): HTMLElement {
    return fixture.nativeElement as HTMLElement;
  }

  function fill(email: string, password: string): void {
    for (const [id, value] of [
      ['#register-email', email],
      ['#register-password', password],
    ]) {
      const input = element().querySelector<HTMLInputElement>(id)!;
      input.value = value;
      input.dispatchEvent(new Event('input'));
    }
    fixture.detectChanges();
  }

  function submitButton(): HTMLButtonElement {
    return element().querySelector<HTMLButtonElement>('.auth-submit')!;
  }

  it('refuses a password shorter than the server would accept', () => {
    // Caught here so the obvious mistake costs no round trip. The rest of
    // Identity's rules stay on the server rather than being duplicated.
    fill('nikola@test.rs', 'Test12!');
    expect(submitButton().disabled).toBe(true);

    fill('nikola@test.rs', 'Test1234!');
    expect(submitButton().disabled).toBe(false);
  });

  it('states the password rule before it is broken', () => {
    const hint = element().querySelector('#register-password-hint');

    expect(hint?.textContent?.trim()).toBe('auth.register.passwordHint');
  });

  it('signs the new account in rather than asking for the same details again', () => {
    const tokens = TestBed.inject(TokenStorage);
    const navigate = vi.spyOn(TestBed.inject(Router), 'navigateByUrl');

    fill('nikola@test.rs', 'Test1234!');
    submitButton().click();
    http.expectOne(ENDPOINT).flush(SESSION);

    expect(tokens.accessToken()).toBe(SESSION.accessToken);
    expect(navigate).toHaveBeenCalledWith('/projects');
  });

  it("shows a taken address under the email field, not as the form's problem", () => {
    fill('nikola@test.rs', 'Test1234!');
    submitButton().click();

    http
      .expectOne(ENDPOINT)
      .flush(
        { errors: { Email: ["Email 'nikola@test.rs' is already taken."] } },
        { status: 400, statusText: 'Bad Request' },
      );
    fixture.detectChanges();

    const fieldError = element().querySelector('#register-email-error');

    // The server's wording, shown as it arrived: it names the address, which a
    // translated generic message could not.
    expect(fieldError?.textContent?.trim()).toBe("Email 'nikola@test.rs' is already taken.");
    expect(element().querySelector('.auth-summary')).toBeNull();
    expect(element().querySelector('#register-email')?.getAttribute('aria-invalid')).toBe('true');
  });
});
