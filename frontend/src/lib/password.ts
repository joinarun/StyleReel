export function validatePasswordChange(password:string,confirmation:string,current?:string):string|null{
 if(password.length<12)return 'Use at least 12 characters for your new password.';
 if(password.length>128)return 'Use no more than 128 characters for your password.';
 if(password!==confirmation)return 'Your new passwords do not match.';
 if(current&&current===password)return 'Choose a different password from your current one.';
 return null;
}
